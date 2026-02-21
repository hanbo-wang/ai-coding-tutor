import logging
from typing import Optional

import numpy as np

from app.ai.embedding_cohere import CohereEmbeddingService
from app.ai.embedding_voyage import VoyageEmbeddingService

logger = logging.getLogger(__name__)


def _cosine_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    """Cosine similarity between two vectors using NumPy."""
    norm_a = np.linalg.norm(vec_a)
    norm_b = np.linalg.norm(vec_b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(vec_a, vec_b) / (norm_a * norm_b))


def _max_similarity(matrix: np.ndarray, vec: np.ndarray) -> float:
    """Max cosine similarity between a vector and each row of a matrix.

    Uses a single matrix-vector multiply instead of N individual dot products.
    """
    norms = np.linalg.norm(matrix, axis=1)
    vec_norm = np.linalg.norm(vec)
    if vec_norm == 0:
        return 0.0
    sims = matrix @ vec / (norms * vec_norm + 1e-10)
    return float(np.max(sims))


class EmbeddingService:
    def __init__(
        self,
        provider: str,
        cohere_api_key: str = "",
        voyage_api_key: str = "",
    ):
        cohere = CohereEmbeddingService(cohere_api_key) if cohere_api_key else None
        voyage = VoyageEmbeddingService(voyage_api_key) if voyage_api_key else None

        if provider == "voyage":
            self._provider = voyage or cohere
            self._fallback = cohere if voyage else None
        else:
            # "cohere" or any other value
            self._provider = cohere or voyage
            self._fallback = voyage if cohere else None

        if self._provider is None:
            raise RuntimeError("No embedding API key configured")
        self._greeting_embeddings: Optional[np.ndarray] = None  # (N, D)
        self._topic_embeddings: Optional[np.ndarray] = None  # (M, D)
        self._elaboration_embeddings: Optional[np.ndarray] = None  # (E, D)
        self._initialized = False
        # In-memory cache: text -> embedding (bounded to 512 entries)
        self._cache: dict[str, list[float]] = {}
        self._cache_max = 512

    async def close(self) -> None:
        """Close the underlying embedding providers."""
        await self._provider.close()
        if self._fallback:
            await self._fallback.close()

    async def initialize(self) -> None:
        """Pre-embed greeting, topic, and elaboration anchors in a single batch."""
        if self._initialized:
            return

        greeting_texts = [
            "hello", "hi", "hey", "good morning", "good afternoon",
            "good evening", "how are you", "what's up", "hi there",
            "hey there", "hello there", "good day", "howdy", "greetings",
        ]
        topic_texts = [
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
        elaboration_texts = [
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

        all_texts = greeting_texts + topic_texts + elaboration_texts
        all_embeddings = await self._embed_with_fallback(all_texts)
        if not all_embeddings:
            logger.error("Failed to initialise embedding service: no provider available")
            return

        n_greetings = len(greeting_texts)
        n_topics = len(topic_texts)
        self._greeting_embeddings = np.array(all_embeddings[:n_greetings])
        self._topic_embeddings = np.array(all_embeddings[n_greetings:n_greetings + n_topics])
        self._elaboration_embeddings = np.array(all_embeddings[n_greetings + n_topics:])
        self._initialized = True
        logger.info(
            "Embedding service initialised: %d greetings, %d topics, %d elaboration, dim=%d",
            self._greeting_embeddings.shape[0],
            self._topic_embeddings.shape[0],
            self._elaboration_embeddings.shape[0],
            self._greeting_embeddings.shape[1],
        )

    async def _embed_with_fallback(self, texts: list[str]) -> list[list[float]] | None:
        """Try the primary provider, fall back to Voyage on failure."""
        try:
            return await self._provider.embed_batch(texts)
        except Exception as e:
            logger.warning("Primary embedding provider failed: %s", e)

        if self._fallback:
            try:
                return await self._fallback.embed_batch(texts)
            except Exception as e:
                logger.error("Fallback embedding provider also failed: %s", e)

        return None

    async def embed_text(self, text: str) -> Optional[list[float]]:
        """Return an embedding vector, using cache when available."""
        key = text.strip().lower()
        if key in self._cache:
            return self._cache[key]

        result = await self._embed_with_fallback([text])
        if result:
            self._put_cache(key, result[0])
            return result[0]
        return None

    async def embed_image(
        self, image_bytes: bytes, content_type: str
    ) -> Optional[list[float]]:
        """Return an embedding vector for an image attachment."""
        try:
            if hasattr(self._provider, "embed_image"):
                result = await self._provider.embed_image(image_bytes, content_type)
                if result:
                    return result
        except Exception as e:
            logger.warning("Primary image embedding provider failed: %s", e)

        if self._fallback and hasattr(self._fallback, "embed_image"):
            try:
                return await self._fallback.embed_image(image_bytes, content_type)
            except Exception as e:
                logger.error("Fallback image embedding provider failed: %s", e)

        return None

    def _put_cache(self, key: str, embedding: list[float]) -> None:
        """Insert into cache, evicting oldest entry if full."""
        if len(self._cache) >= self._cache_max:
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]
        self._cache[key] = embedding

    # ── Pre-filter checks (operate on a pre-computed embedding) ──

    def check_greeting(self, embedding: list[float]) -> bool:
        """Check if the embedding matches a greeting.

        Calibrated for Cohere embed-v4.0 (256d) with 14 greeting anchors.
        """
        if self._greeting_embeddings is None:
            return False
        vector = np.array(embedding)
        if self._greeting_embeddings.shape[1] != vector.shape[0]:
            return False
        return _max_similarity(self._greeting_embeddings, vector) > 0.75

    def check_off_topic(self, embedding: list[float]) -> bool:
        """Check if the embedding is off-topic.

        Calibrated for Cohere embed-v4.0 (256d) with 53 topic anchors.
        """
        if self._topic_embeddings is None:
            return False
        vector = np.array(embedding)
        if self._topic_embeddings.shape[1] != vector.shape[0]:
            return False
        return _max_similarity(self._topic_embeddings, vector) < 0.30

    def check_same_problem(
        self, current_embedding: list[float], previous_embedding: list[float]
    ) -> bool:
        """Check if the current message is a follow-up on the same problem.

        Compares current message embedding against previous Q+A context embedding.
        Calibrated for Cohere embed-v4.0 (256d).
        """
        current = np.array(current_embedding)
        previous = np.array(previous_embedding)
        if current.shape != previous.shape:
            return False
        return _cosine_similarity(current, previous) > 0.35

    def check_elaboration_request(self, embedding: list[float]) -> bool:
        """Check if the message is a generic elaboration request.

        Matches against 25 elaboration anchors covering: confusion, requests
        for detail, step-by-step, examples, hints, clarification, continuation.
        Calibrated for Cohere embed-v4.0 (256d).
        """
        if self._elaboration_embeddings is None:
            return False
        vector = np.array(embedding)
        if self._elaboration_embeddings.shape[1] != vector.shape[0]:
            return False
        return _max_similarity(self._elaboration_embeddings, vector) > 0.50

    @staticmethod
    def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
        array_a = np.array(vec_a)
        array_b = np.array(vec_b)
        if array_a.shape != array_b.shape:
            return 0.0
        return _cosine_similarity(array_a, array_b)

    @staticmethod
    def combine_embeddings(vectors: list[list[float]]) -> list[float] | None:
        """Average vectors into one embedding for multimodal comparisons."""
        if not vectors:
            return None

        arrays = [np.array(vec) for vec in vectors if vec]
        if not arrays:
            return None

        dimension = arrays[0].shape[0]
        compatible = [arr for arr in arrays if arr.shape[0] == dimension]
        if not compatible:
            return None

        merged = np.mean(np.vstack(compatible), axis=0)
        return merged.tolist()
