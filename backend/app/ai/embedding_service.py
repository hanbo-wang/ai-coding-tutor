import logging
from typing import Optional

import numpy as np

from app.ai.embedding_cohere import CohereEmbeddingService
from app.ai.embedding_vertex import VertexEmbeddingService
from app.ai.embedding_voyage import VoyageEmbeddingService
from app.ai.google_auth import (
    GoogleServiceAccountTokenProvider,
    resolve_google_credentials_path,
    resolve_google_project_id,
)
from app.ai.model_registry import validate_supported_embedding_model

logger = logging.getLogger(__name__)

GREETING_ANCHORS = [
    "hello",
    "hi",
    "hey",
    "good morning",
    "good afternoon",
    "good evening",
    "how are you",
    "what's up",
    "hi there",
    "hey there",
    "hello there",
    "good day",
    "howdy",
    "greetings",
]

# Topic anchors are intentionally specific (phrases, not mostly single words) to
# reduce false matches on general chat with Vertex `multimodalembedding@001`.
TOPIC_ANCHORS = [
    "python list sorting algorithm",
    "binary search algorithm implementation",
    "linked list data structure operations",
    "recursion base case recursive function",
    "object oriented programming classes and methods",
    "debugging code and reading error messages",
    "syntax error type error index error debugging",
    "for loop if statement Python function arguments",
    "algorithm time complexity and efficiency",
    "data structures arrays stacks queues trees",
    "pytest unit test assertions and test failures",
    "runtime error and stack trace analysis",
    "implementing an algorithm in code",
    "calculus derivative and integral problem solving",
    "differential equation solving method",
    "Taylor series expansion approximation",
    "proof by induction mathematics problem",
    "probability and statistics calculation",
    "Bayes theorem conditional probability",
    "trigonometry identities and functions",
    "linear algebra matrix operations",
    "eigenvalue and eigenvector computation",
    "determinant of a matrix",
    "matrix decomposition and factorisation",
    "LU factorisation Gaussian elimination",
    "singular value decomposition matrix",
    "numerical methods root finding",
    "bisection method root finding",
    "Newton Raphson method root finding",
    "Euler method numerical ODE",
    "Runge Kutta method ODE solver",
    "solve ODE using Runge Kutta method",
    "initial value problem numerical method",
    "boundary value problem numerical method",
    "finite difference method numerical solution",
    "numerical integration trapezoidal rule",
    "error analysis convergence rate numerical method",
    "Fourier transform signal processing",
    "discrete Fourier transform FFT algorithm",
    "spectral analysis frequency domain signal",
    "Newton law mechanics force motion",
    "thermodynamics energy entropy temperature",
    "electromagnetism electric and magnetic fields",
    "quantum mechanics Schrodinger equation wavefunction",
    "conservation of energy physics problem",
    "wave equation oscillation and propagation",
    "optimisation objective function constraints",
    "computational science numerical simulation",
    "scientific computing in Python",
    "data analysis with arrays and matrices",
    "graph algorithm shortest path and traversal",
    "dynamic programming algorithm recurrence relation",
]

# Explicit off-topic anchors allow a relative similarity check (off-topic vs topic)
# which works much better than a single low-topic threshold on Vertex embeddings.
OFF_TOPIC_ANCHORS = [
    "weather forecast and temperature today",
    "rain forecast and weather report",
    "football match result and sports scores",
    "basketball score and match highlights",
    "restaurant recommendation and food places",
    "pizza restaurant review and takeaway",
    "movie recommendation and film review",
    "tv show recommendation and entertainment news",
    "tell me a joke or funny story",
    "celebrity gossip and entertainment updates",
    "current time and date question",
    "what time is it right now",
    "personal questions about your name or age",
    "who are you and what is your name",
    "relationship advice and dating questions",
    "life advice and career choice guidance",
    "travel planning and holiday recommendations",
    "shopping advice and product recommendations",
    "music recommendation and songs",
    "general chit chat small talk conversation",
]

ELABORATION_ANCHORS = [
    # Not understanding
    "I don't understand",
    "I'm confused",
    "that doesn't make sense",
    "I still don't get it",
    # Request more detail
    "explain more",
    "can you elaborate",
    "give me more details",
    "tell me more",
    # Step-by-step
    "show me step by step",
    "break it down for me",
    "walk me through it",
    # Examples
    "show me an example",
    "give me an example",
    # Hints/answers
    "give me a hint",
    "show me the answer",
    "just tell me",
    # Clarification
    "what do you mean",
    "can you explain that again",
    "could you clarify",
    # Continuation
    "go on",
    "continue",
    "what's next",
    "and then what",
    # Simple interrogatives
    "why",
    "how",
]

EMBEDDING_THRESHOLDS = {
    # Provider-specific semantic thresholds calibrated with
    # backend/tests/test_semantic_thresholds.py.
    "vertex": {
        "greeting_min_similarity": 0.915,
        # Fallback rule if off-topic anchors are unavailable.
        "off_topic_max_similarity": 0.68,
        # Primary Vertex off-topic rule: strong off-topic anchor match with
        # clear margin over the best topic anchor.
        "off_topic_negative_min_similarity": 0.80,
        "off_topic_margin_min_similarity": 0.07,
        "same_problem_min_similarity": 0.73,
        "elaboration_min_similarity": 0.88,
    },
    # Shared fallback profile for optional non-Vertex embedding semantics.
    "fallback": {
        "greeting_min_similarity": 0.75,
        "off_topic_max_similarity": 0.30,
        "same_problem_min_similarity": 0.35,
        "elaboration_min_similarity": 0.50,
    },
}


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
        google_application_credentials: str = "",
        google_application_credentials_host_path: str = "",
        google_cloud_project_id: str = "",
        vertex_location: str = "us-central1",
        vertex_model_id: str = "multimodalembedding@001",
        cohere_api_key: str = "",
        voyage_api_key: str = "",
    ):
        vertex = None
        if google_application_credentials or google_application_credentials_host_path:
            try:
                resolved_creds_path = resolve_google_credentials_path(
                    google_application_credentials,
                    google_application_credentials_host_path,
                )
                vertex_model = validate_supported_embedding_model("vertex", vertex_model_id)
                token_provider = GoogleServiceAccountTokenProvider(resolved_creds_path)
                vertex = VertexEmbeddingService(
                    token_provider=token_provider,
                    project_id=resolve_google_project_id(
                        resolved_creds_path,
                        google_cloud_project_id,
                    ),
                    location=vertex_location,
                    model_id=vertex_model,
                )
            except Exception as exc:
                logger.warning(
                    "Vertex embedding provider unavailable during initialisation, "
                    "continuing with configured fallbacks: %s",
                    exc,
                )
        cohere = CohereEmbeddingService(cohere_api_key) if cohere_api_key else None
        voyage = VoyageEmbeddingService(voyage_api_key) if voyage_api_key else None

        provider = provider.lower()
        available = {
            "vertex": vertex,
            "cohere": cohere,
            "voyage": voyage,
        }
        preferred_order = {
            "vertex": ["vertex", "cohere", "voyage"],
            "cohere": ["cohere", "voyage", "vertex"],
            "voyage": ["voyage", "cohere", "vertex"],
        }.get(provider, ["vertex", "cohere", "voyage"])
        ordered = [available[name] for name in preferred_order if available.get(name)]
        if not ordered:
            raise RuntimeError("No embedding API key configured")
        self._provider = ordered[0]
        self._fallbacks = ordered[1:]
        selected_provider_name = next(
            (name for name in preferred_order if available.get(name) is self._provider),
            "vertex",
        )
        threshold_profile_key = "vertex" if selected_provider_name == "vertex" else "fallback"
        self._threshold_profile = EMBEDDING_THRESHOLDS[threshold_profile_key]
        self._greeting_embeddings: Optional[np.ndarray] = None  # (N, D)
        self._topic_embeddings: Optional[np.ndarray] = None  # (M, D)
        self._off_topic_embeddings: Optional[np.ndarray] = None  # (O, D)
        self._elaboration_embeddings: Optional[np.ndarray] = None  # (E, D)
        self._initialized = False
        # In-memory cache: text -> embedding (bounded to 512 entries)
        self._cache: dict[str, list[float]] = {}
        self._cache_max = 512

    async def close(self) -> None:
        """Close the underlying embedding providers."""
        await self._provider.close()
        for fallback in self._fallbacks:
            await fallback.close()

    async def initialize(self) -> None:
        """Pre-embed semantic anchors in provider-agnostic batches."""
        if self._initialized:
            return

        greeting_texts = GREETING_ANCHORS
        topic_texts = TOPIC_ANCHORS
        off_topic_texts = OFF_TOPIC_ANCHORS
        elaboration_texts = ELABORATION_ANCHORS

        all_texts = greeting_texts + topic_texts + off_topic_texts + elaboration_texts
        all_embeddings = await self._embed_texts_batched(all_texts)
        if not all_embeddings:
            logger.error("Failed to initialise embedding service: no provider available")
            return

        n_greetings = len(greeting_texts)
        n_topics = len(topic_texts)
        n_off_topics = len(off_topic_texts)
        self._greeting_embeddings = np.array(all_embeddings[:n_greetings])
        self._topic_embeddings = np.array(all_embeddings[n_greetings:n_greetings + n_topics])
        off_start = n_greetings + n_topics
        self._off_topic_embeddings = np.array(all_embeddings[off_start:off_start + n_off_topics])
        self._elaboration_embeddings = np.array(all_embeddings[off_start + n_off_topics:])
        self._initialized = True
        logger.info(
            "Embedding service initialised: %d greetings, %d topics, %d off-topic, %d elaboration, dim=%d",
            self._greeting_embeddings.shape[0],
            self._topic_embeddings.shape[0],
            self._off_topic_embeddings.shape[0],
            self._elaboration_embeddings.shape[0],
            self._greeting_embeddings.shape[1],
        )

    async def _embed_texts_batched(self, texts: list[str], batch_size: int = 64) -> list[list[float]] | None:
        """Embed texts in batches without mixing providers across chunks."""
        providers = [self._provider, *self._fallbacks]
        for provider in providers:
            all_embeddings: list[list[float]] = []
            try:
                for i in range(0, len(texts), batch_size):
                    chunk = texts[i : i + batch_size]
                    result = await provider.embed_batch(chunk)
                    if not result or len(result) != len(chunk):
                        raise RuntimeError(
                            f"Provider returned {len(result) if result else 0} embeddings for {len(chunk)} texts"
                        )
                    all_embeddings.extend(result)
                return all_embeddings
            except Exception as e:
                if provider is self._provider:
                    logger.warning("Primary embedding provider failed during anchor initialisation: %s", e)
                else:
                    logger.error("Fallback embedding provider failed during anchor initialisation: %s", e)
        return None

    async def _embed_with_fallback(self, texts: list[str]) -> list[list[float]] | None:
        """Try the primary provider, then any configured fallbacks."""
        try:
            return await self._provider.embed_batch(texts)
        except Exception as e:
            logger.warning("Primary embedding provider failed: %s", e)
        for fallback in self._fallbacks:
            try:
                return await fallback.embed_batch(texts)
            except Exception as e:
                logger.error("Fallback embedding provider failed: %s", e)

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

        for fallback in self._fallbacks:
            if not hasattr(fallback, "embed_image"):
                continue
            try:
                return await fallback.embed_image(image_bytes, content_type)
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

        Uses provider-specific thresholds with 256d vectors and 14 greeting anchors.
        """
        if self._greeting_embeddings is None:
            return False
        vector = np.array(embedding)
        if self._greeting_embeddings.shape[1] != vector.shape[0]:
            return False
        threshold = self._threshold_profile["greeting_min_similarity"]
        return _max_similarity(self._greeting_embeddings, vector) > threshold

    def check_off_topic(self, embedding: list[float]) -> bool:
        """Check if the embedding is off-topic.

        Vertex uses topic vs off-topic anchor comparison with a margin. Other
        providers use the legacy low-topic-threshold rule.
        """
        if self._topic_embeddings is None:
            return False
        vector = np.array(embedding)
        if self._topic_embeddings.shape[1] != vector.shape[0]:
            return False
        topic_max = _max_similarity(self._topic_embeddings, vector)

        off_topic_min = self._threshold_profile.get("off_topic_negative_min_similarity")
        margin_min = self._threshold_profile.get("off_topic_margin_min_similarity")
        if (
            isinstance(off_topic_min, (int, float))
            and isinstance(margin_min, (int, float))
            and self._off_topic_embeddings is not None
            and self._off_topic_embeddings.shape[1] == vector.shape[0]
        ):
            off_topic_max = _max_similarity(self._off_topic_embeddings, vector)
            if (
                off_topic_max >= float(off_topic_min)
                and (off_topic_max - topic_max) >= float(margin_min)
            ):
                return True

        threshold = self._threshold_profile["off_topic_max_similarity"]
        return topic_max < threshold

    def check_same_problem(
        self, current_embedding: list[float], previous_embedding: list[float]
    ) -> bool:
        """Check if the current message is a follow-up on the same problem.

        Compares current message embedding against previous Q+A context embedding.
        Uses provider-specific thresholds for 256d vectors.
        """
        current = np.array(current_embedding)
        previous = np.array(previous_embedding)
        if current.shape != previous.shape:
            return False
        threshold = self._threshold_profile["same_problem_min_similarity"]
        return _cosine_similarity(current, previous) > threshold

    def check_elaboration_request(self, embedding: list[float]) -> bool:
        """Check if the message is a generic elaboration request.

        Matches against 25 elaboration anchors covering: confusion, requests
        for detail, step-by-step, examples, hints, clarification, continuation.
        Uses provider-specific thresholds for 256d vectors.
        """
        if self._elaboration_embeddings is None:
            return False
        vector = np.array(embedding)
        if self._elaboration_embeddings.shape[1] != vector.shape[0]:
            return False
        threshold = self._threshold_profile["elaboration_min_similarity"]
        return _max_similarity(self._elaboration_embeddings, vector) > threshold

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
