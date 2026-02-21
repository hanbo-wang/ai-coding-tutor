"""Semantic recognition threshold calibration test.

Embeds test phrases via Cohere Embed v4 (256 dimensions) and measures cosine
similarity against the greeting templates, topic anchors, and elaboration
anchors used by EmbeddingService. Also tests same-problem detection with
Q+A context pairs.

Usage:
    cd backend
    python -m tests.test_semantic_thresholds
"""

import asyncio
import os
import sys

import numpy as np

# Allow running from the backend directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

from app.ai.embedding_cohere import CohereEmbeddingService


def cosine_similarity(a: list[float], b: list[float]) -> float:
    va, vb = np.array(a), np.array(b)
    na, nb = np.linalg.norm(va), np.linalg.norm(vb)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


def max_similarity(anchors: list[list[float]], vec: list[float]) -> float:
    mat = np.array(anchors)
    v = np.array(vec)
    norms = np.linalg.norm(mat, axis=1)
    v_norm = np.linalg.norm(v)
    if v_norm == 0:
        return 0.0
    sims = mat @ v / (norms * v_norm + 1e-10)
    return float(np.max(sims))


# ── Reference anchors (same as embedding_service.py) ──

GREETING_TEMPLATES = [
    "hello", "hi", "hey", "good morning", "good afternoon",
    "good evening", "how are you", "what's up", "hi there",
    "hey there", "hello there", "good day", "howdy", "greetings",
]

TOPIC_ANCHORS = [
    # Programming
    "programming", "coding", "Python", "algorithm", "data structure",
    "recursion", "sorting algorithm", "object-oriented programming",
    "debugging code", "error in my code", "syntax error",
    "code not working", "how to implement",
    # Mathematics general
    "mathematics", "calculus", "statistics",
    "probability", "trigonometry", "formula derivation",
    # Linear algebra
    "linear algebra", "matrix", "eigenvalue", "eigenvector",
    "matrix decomposition", "LU factorization", "Gaussian elimination",
    # Calculus and analysis
    "integral", "derivative", "differential equation", "Taylor series",
    # Numerical methods
    "numerical methods", "root finding", "bisection method",
    "Newton-Raphson method", "Euler method", "Runge-Kutta method",
    "initial value problem", "boundary value problem",
    "finite difference method", "numerical integration",
    # Fourier analysis
    "Fourier transform", "discrete Fourier transform",
    "FFT", "spectral analysis",
    # Physics
    "physics", "mechanics", "thermodynamics", "electromagnetism",
    "quantum mechanics", "wave equation", "simulation",
    # Applied
    "optimization", "computational science",
]

ELABORATION_ANCHORS = [
    # Not understanding
    "I don't understand", "I'm confused",
    "that doesn't make sense", "I still don't get it",
    # Request more detail
    "explain more", "can you elaborate",
    "give me more details", "tell me more",
    # Step-by-step
    "show me step by step", "break it down for me", "walk me through it",
    # Examples
    "show me an example", "give me an example",
    # Hints/answers
    "give me a hint", "show me the answer", "just tell me",
    # Clarification
    "what do you mean", "can you explain that again", "could you clarify",
    # Continuation
    "go on", "continue", "what's next", "and then what",
    # Simple interrogatives
    "why", "how",
]

# ── Test phrases ──

GREETING_TRUE = [
    "hello",
    "hi there",
    "hey",
    "good morning",
    "howdy",
    "what's up",
    "yo",
    "greetings",
    "hello hello",
    "hi hi hi",
    "good day",
    "hey there",
    "hello there",
    "good afternoon",
]

GREETING_FALSE_POSITIVES = [
    "say hello world in Python",
    "hello world program",
    "print hello",
    "implement a greeting function",
    "the hello protocol",
    "good morning routine algorithm",
    "greetings card design in CSS",
]

GREETING_WITH_QUESTION = [
    "Hello, how do I reverse a list?",
    "Hi, can you help me with Python?",
    "Hey, what is calculus?",
    "Good morning, I need help with my code",
    "Hi there, explain eigenvalues please",
]

ON_TOPIC = [
    # Programming
    "how to sort a list in Python",
    "explain binary search",
    "implement a linked list",
    "how do I debug a segfault",
    "what is a recursive function",
    "explain object-oriented programming",
    "how to read a CSV file in Python",
    "what does this error mean: IndexError",
    # Mathematics
    "what is the derivative of x squared",
    "solve this differential equation",
    "explain eigenvalues",
    "how to compute a definite integral",
    "what is the determinant of a matrix",
    "explain Bayes theorem",
    "how to prove by induction",
    # Physics
    "Newton's second law",
    "explain the Schrodinger equation",
    "what is conservation of energy",
    "how does electromagnetic induction work",
    "explain the second law of thermodynamics",
    # Numerical computation course
    "find the eigenvalues of this matrix",
    "how does LU factorization work",
    "explain the bisection method",
    "solve this ODE using Runge-Kutta",
    "what is an initial value problem",
    "explain the boundary value problem",
    "compute the Fourier transform of this signal",
    "what is the FFT algorithm",
    "how to apply Newton-Raphson method",
    "explain finite difference method",
    "numerical integration using trapezoidal rule",
    "singular value decomposition of a matrix",
]

OFF_TOPIC = [
    "what's the weather today",
    "tell me a joke",
    "who won the football",
    "best pizza in London",
    "what's your name",
    "how old are you",
    "what is love",
    "recommend a good movie",
    "what time is it",
    "what career should I choose",
]

BORDERLINE = [
    "what is machine learning",
    "how does AI work",
    "explain neural networks",
    "what is computer science",
    "help me with my homework",
    "I have an exam tomorrow",
    "can you help me study",
    "translate this to French",
]

# Elaboration detection test phrases (variations, NOT exact anchors)
ELABORATION_TRUE = [
    "I really don't understand this",
    "I'm so confused right now",
    "that makes no sense to me",
    "can you explain that more",
    "please elaborate on that",
    "show me how step by step",
    "give me an example please",
    "just give me the answer",
    "what does that mean",
    "please continue",
    "why is that",
    "how come",
    "solve this equation",
]

ELABORATION_FALSE = [
    "what is calculus",
    "explain eigenvalues",
    "how to sort a list",
    "what is recursion",
    "define a matrix",
    "what is the FFT",
]

# Same-problem pairs: (question, answer_snippet, follow_up)
# The follow-up should be detected as same-problem when compared against Q+A context
SAME_PROBLEM_QA_PAIRS = [
    (
        "how to reverse a list in Python",
        "You can use slicing with [::-1] or the built-in reversed() function.",
        "can you explain the reversal more?",
    ),
    (
        "what is the derivative of sin(x)",
        "The derivative of sin(x) is cos(x). This follows from the limit definition.",
        "I don't understand, show me step by step",
    ),
    (
        "implement binary search",
        "Binary search works by repeatedly dividing the search interval in half. Check the middle element.",
        "what about the edge cases for binary search?",
    ),
    (
        "how to sort a list in Python",
        "You could use quicksort or mergesort. Python's built-in sorted() uses Timsort.",
        "tell me more about mergesort",
    ),
    (
        "explain the Schrodinger equation",
        "The time-dependent Schrodinger equation describes the wavefunction evolution: ih_bar d/dt psi = H psi.",
        "can you show the derivation?",
    ),
]

DIFFERENT_PROBLEM_PAIRS = [
    ("how to reverse a list in Python", "what is the derivative of sin(x)"),
    ("implement binary search", "explain Newton's second law"),
    ("explain eigenvalues", "how to read a CSV file in Python"),
    ("what is conservation of energy", "explain object-oriented programming"),
]

VAGUE_FOLLOWUPS_BASE = "how to reverse a list in Python"
VAGUE_FOLLOWUPS_BASE_ANSWER = (
    "You can use slicing with [::-1] or the built-in reversed() function. "
    "The slice notation creates a new list in reverse order."
)
VAGUE_FOLLOWUPS = [
    "I don't understand",
    "explain more",
    "show me the answer",
    "can you elaborate?",
    "why?",
    "what do you mean",
]


async def main() -> None:
    api_key = os.environ.get("COHERE_API_KEY", "")
    if not api_key:
        print("ERROR: COHERE_API_KEY not set in environment or .env file")
        sys.exit(1)

    provider = CohereEmbeddingService(api_key)

    try:
        # Embed all anchors
        print(f"Embedding {len(GREETING_TEMPLATES)} greeting, "
              f"{len(TOPIC_ANCHORS)} topic, "
              f"{len(ELABORATION_ANCHORS)} elaboration anchors (256d)...")
        anchor_texts = GREETING_TEMPLATES + TOPIC_ANCHORS + ELABORATION_ANCHORS
        anchor_embs = await provider.embed_batch(anchor_texts)
        greeting_embs = anchor_embs[:len(GREETING_TEMPLATES)]
        topic_embs = anchor_embs[len(GREETING_TEMPLATES):len(GREETING_TEMPLATES) + len(TOPIC_ANCHORS)]
        elaboration_embs = anchor_embs[len(GREETING_TEMPLATES) + len(TOPIC_ANCHORS):]

        print(f"  Dimension: {len(greeting_embs[0])}")

        # Collect all test phrases — split into batches of 96 (Cohere limit)
        all_tests = (
            GREETING_TRUE
            + GREETING_FALSE_POSITIVES
            + GREETING_WITH_QUESTION
            + ON_TOPIC
            + OFF_TOPIC
            + BORDERLINE
            + ELABORATION_TRUE
            + ELABORATION_FALSE
        )
        batch_size = 96
        print(f"Embedding {len(all_tests)} test phrases...")
        all_embs: list[list[float]] = []
        for i in range(0, len(all_tests), batch_size):
            batch = all_tests[i : i + batch_size]
            all_embs.extend(await provider.embed_batch(batch))

        idx = 0

        def next_embs(n: int) -> list[list[float]]:
            nonlocal idx
            result = all_embs[idx : idx + n]
            idx += n
            return result

        greeting_true_embs = next_embs(len(GREETING_TRUE))
        greeting_fp_embs = next_embs(len(GREETING_FALSE_POSITIVES))
        greeting_q_embs = next_embs(len(GREETING_WITH_QUESTION))
        on_topic_embs = next_embs(len(ON_TOPIC))
        off_topic_embs = next_embs(len(OFF_TOPIC))
        borderline_embs = next_embs(len(BORDERLINE))
        elab_true_embs = next_embs(len(ELABORATION_TRUE))
        elab_false_embs = next_embs(len(ELABORATION_FALSE))

        def max_greeting_sim(emb: list[float]) -> float:
            return max_similarity(greeting_embs, emb)

        def max_topic_sim(emb: list[float]) -> float:
            return max_similarity(topic_embs, emb)

        def max_elab_sim(emb: list[float]) -> float:
            return max_similarity(elaboration_embs, emb)

        # ── 1. GREETING DETECTION ──

        print("\n" + "=" * 70)
        print("1A. GREETING DETECTION (should be HIGH)")
        print("=" * 70)
        print(f"{'Phrase':<45} {'Max Sim':>8}")
        print("-" * 55)
        for phrase, emb in zip(GREETING_TRUE, greeting_true_embs):
            sim = max_greeting_sim(emb)
            print(f"{phrase:<45} {sim:>8.4f}")

        print("\n" + "=" * 70)
        print("1B. GREETING FALSE POSITIVES (should be LOW)")
        print("=" * 70)
        print(f"{'Phrase':<45} {'Max Sim':>8}")
        print("-" * 55)
        for phrase, emb in zip(GREETING_FALSE_POSITIVES, greeting_fp_embs):
            sim = max_greeting_sim(emb)
            print(f"{phrase:<45} {sim:>8.4f}")

        print("\n" + "=" * 70)
        print("1C. GREETING + QUESTION (should NOT trigger greeting)")
        print("=" * 70)
        print(f"{'Phrase':<45} {'Max Sim':>8}")
        print("-" * 55)
        for phrase, emb in zip(GREETING_WITH_QUESTION, greeting_q_embs):
            sim = max_greeting_sim(emb)
            print(f"{phrase:<45} {sim:>8.4f}")

        # ── 2. OFF-TOPIC DETECTION ──

        print("\n" + "=" * 70)
        print("2A. ON-TOPIC MESSAGES (should be HIGH)")
        print("=" * 70)
        print(f"{'Phrase':<45} {'Max Sim':>8}")
        print("-" * 55)
        for phrase, emb in zip(ON_TOPIC, on_topic_embs):
            sim = max_topic_sim(emb)
            print(f"{phrase:<45} {sim:>8.4f}")

        print("\n" + "=" * 70)
        print("2B. OFF-TOPIC MESSAGES (should be LOW)")
        print("=" * 70)
        print(f"{'Phrase':<45} {'Max Sim':>8}")
        print("-" * 55)
        for phrase, emb in zip(OFF_TOPIC, off_topic_embs):
            sim = max_topic_sim(emb)
            print(f"{phrase:<45} {sim:>8.4f}")

        print("\n" + "=" * 70)
        print("2C. BORDERLINE MESSAGES")
        print("=" * 70)
        print(f"{'Phrase':<45} {'Max Sim':>8}")
        print("-" * 55)
        for phrase, emb in zip(BORDERLINE, borderline_embs):
            sim = max_topic_sim(emb)
            print(f"{phrase:<45} {sim:>8.4f}")

        # ── 3. SAME-PROBLEM DETECTION (Q+A context) ──

        print("\n" + "=" * 70)
        print("3A. SAME-PROBLEM PAIRS with Q+A context (should be HIGH)")
        print("=" * 70)
        print(f"{'Follow-up':<45} {'vs Q+A':>8}")
        print("-" * 55)
        for question, answer, follow_up in SAME_PROBLEM_QA_PAIRS:
            combined = question + "\n" + answer
            embs = await provider.embed_batch([combined, follow_up])
            sim_qa = cosine_similarity(embs[1], embs[0])
            print(f"{follow_up:<45} {sim_qa:>8.4f}")

        print("\n" + "=" * 70)
        print("3B. DIFFERENT-PROBLEM PAIRS (should be LOW)")
        print("=" * 70)
        print(f"{'Question A':<35} {'Question B':<35} {'Sim':>8}")
        print("-" * 80)
        for q_a, q_b in DIFFERENT_PROBLEM_PAIRS:
            embs = await provider.embed_batch([q_a, q_b])
            sim = cosine_similarity(embs[0], embs[1])
            print(f"{q_a:<35} {q_b:<35} {sim:>8.4f}")

        print("\n" + "=" * 70)
        print("3C. VAGUE FOLLOW-UPS vs Q+A context")
        print(f"    Base Q: \"{VAGUE_FOLLOWUPS_BASE}\"")
        print(f"    Base A: \"{VAGUE_FOLLOWUPS_BASE_ANSWER[:60]}...\"")
        print("=" * 70)
        combined_base = VAGUE_FOLLOWUPS_BASE + "\n" + VAGUE_FOLLOWUPS_BASE_ANSWER
        base_embs = await provider.embed_batch([combined_base])
        base_qa_emb = base_embs[0]
        print(f"{'Follow-up':<45} {'vs Q+A':>8}")
        print("-" * 55)
        for phrase in VAGUE_FOLLOWUPS:
            embs = await provider.embed_batch([phrase])
            sim_qa = cosine_similarity(base_qa_emb, embs[0])
            print(f"{phrase:<45} {sim_qa:>8.4f}")

        # ── 4. ELABORATION REQUEST DETECTION ──

        print("\n" + "=" * 70)
        print("4A. ELABORATION TRUE POSITIVES (should be HIGH)")
        print("=" * 70)
        print(f"{'Phrase':<45} {'Max Sim':>8}")
        print("-" * 55)
        for phrase, emb in zip(ELABORATION_TRUE, elab_true_embs):
            sim = max_elab_sim(emb)
            print(f"{phrase:<45} {sim:>8.4f}")

        print("\n" + "=" * 70)
        print("4B. ELABORATION FALSE POSITIVES (should be LOW)")
        print("=" * 70)
        print(f"{'Phrase':<45} {'Max Sim':>8}")
        print("-" * 55)
        for phrase, emb in zip(ELABORATION_FALSE, elab_false_embs):
            sim = max_elab_sim(emb)
            print(f"{phrase:<45} {sim:>8.4f}")

    finally:
        await provider.close()


if __name__ == "__main__":
    asyncio.run(main())
