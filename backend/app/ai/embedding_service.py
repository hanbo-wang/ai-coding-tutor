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

EMBEDDING_THRESHOLDS = {
    # Provider-specific semantic thresholds calibrated with
    # backend/tests/test_semantic_thresholds.py (text-only calibration corpus).
    "cohere": {
        "greeting_min_similarity": 0.99,
        "off_topic_max_similarity": 0.361,
        "off_topic_negative_min_similarity": 0.65,
        "off_topic_margin_min_similarity": 0.386,
    },
    "vertex": {
        "greeting_min_similarity": 0.935,
        # Backup rule if the relative rule cannot run (for example, anchor matrix unavailable).
        "off_topic_max_similarity": 0.751,
        # Primary relative rule: strong off-topic anchor match with
        # clear margin over the best topic anchor.
        "off_topic_negative_min_similarity": 0.808,
        "off_topic_margin_min_similarity": 0.07,
    },
    "voyage": {
        "greeting_min_similarity": 0.97,
        "off_topic_max_similarity": 0.294,
        "off_topic_negative_min_similarity": 0.57,
        "off_topic_margin_min_similarity": 0.442,
    },
}


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
        vertex_location: str,
        google_application_credentials: str = "",
        google_application_credentials_host_path: str = "",
        google_cloud_project_id: str = "",
        cohere_model_id: str = "",
        vertex_model_id: str = "",
        voyage_model_id: str = "",
        cohere_api_key: str = "",
        voyage_api_key: str = "",
    ):
        cohere = None
        if cohere_api_key:
            cohere_model = validate_supported_embedding_model("cohere", cohere_model_id)
            cohere = CohereEmbeddingService(cohere_api_key, model_id=cohere_model)
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
        voyage = None
        if voyage_api_key:
            voyage_model = validate_supported_embedding_model("voyage", voyage_model_id)
            voyage = VoyageEmbeddingService(voyage_api_key, model_id=voyage_model)

        provider = provider.lower()
        available = {
            "cohere": cohere,
            "vertex": vertex,
            "voyage": voyage,
        }
        preferred_order = {
            "cohere": ["cohere", "vertex", "voyage"],
            "vertex": ["vertex", "cohere", "voyage"],
            "voyage": ["voyage", "cohere", "vertex"],
        }.get(provider, ["cohere", "vertex", "voyage"])
        ordered = [available[name] for name in preferred_order if available.get(name)]
        if not ordered:
            raise RuntimeError("No embedding API key configured")
        self._provider = ordered[0]
        self._fallbacks = ordered[1:]
        selected_provider_name = next(
            (name for name in preferred_order if available.get(name) is self._provider),
            "cohere",
        )
        threshold_profile_key = (
            selected_provider_name if selected_provider_name in EMBEDDING_THRESHOLDS else "cohere"
        )
        self._threshold_profile = EMBEDDING_THRESHOLDS[threshold_profile_key]
        self._greeting_embeddings: Optional[np.ndarray] = None  # (N, D)
        self._topic_embeddings: Optional[np.ndarray] = None  # (M, D)
        self._off_topic_embeddings: Optional[np.ndarray] = None  # (O, D)
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
        all_texts = greeting_texts + topic_texts + off_topic_texts
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
        self._initialized = True
        logger.info(
            "Embedding service initialised: %d greetings, %d topics, %d off-topic, dim=%d",
            self._greeting_embeddings.shape[0],
            self._topic_embeddings.shape[0],
            self._off_topic_embeddings.shape[0],
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

        Uses a provider-specific relative rule (off-topic anchor strength plus
        margin over topic anchors) when configured, with a topic-only fallback
        threshold kept in each profile as a backup.
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

