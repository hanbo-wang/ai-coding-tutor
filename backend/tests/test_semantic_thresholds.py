"""Semantic recognition threshold calibration script (multi-provider, text only).

Embeds test phrases via the configured embedding providers and measures cosine
similarity against the greeting, topic, and off-topic anchors used by
EmbeddingService. The script then performs repeated local threshold sweeps on
the same embeddings to find provider-specific thresholds for the optional
greeting and off-topic filters.

Usage:
    cd backend
    PYTHONPATH=. python -m tests.test_semantic_thresholds
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

# Allow running from the backend directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

from app.ai.embedding_cohere import CohereEmbeddingService  # noqa: E402
from app.ai.embedding_service import (  # noqa: E402
    EMBEDDING_THRESHOLDS,
    GREETING_ANCHORS,
    OFF_TOPIC_ANCHORS,
    TOPIC_ANCHORS,
)
from app.ai.embedding_vertex import VertexEmbeddingService  # noqa: E402
from app.ai.embedding_voyage import VoyageEmbeddingService  # noqa: E402
from app.ai.google_auth import (  # noqa: E402
    GoogleServiceAccountTokenProvider,
    resolve_google_project_id,
)
from app.config import settings  # noqa: E402


GREETING_TRUE = [
    "hello",
    "hi there",
    "hey",
    "good morning",
    "howdy",
    "what's up",
    "yo",
    "greetings",
    "hello there",
]

GREETING_FALSE_POSITIVES = [
    "say hello world in Python",
    "hello world program",
    "implement a greeting function",
    "good morning routine algorithm",
]

GREETING_WITH_QUESTION = [
    "Hello, how do I reverse a list?",
    "Hi, can you help me with Python?",
    "Hey, what is calculus?",
]

ON_TOPIC = [
    "how to sort a list in Python",
    "explain binary search",
    "what is the derivative of x squared",
    "explain eigenvalues",
    "Newton's second law",
    "what is the FFT algorithm",
]

OFF_TOPIC = [
    "what's the weather today",
    "tell me a joke",
    "best pizza in London",
    "what time is it",
    "recommend a good movie",
]

BORDERLINE = [
    "what is machine learning",
    "how does AI work",
    "help me with my homework",
    "translate this to French",
]


@dataclass
class ProviderCalibrationInput:
    provider_name: str
    model_id: str
    greeting_true_scores: list[float]
    greeting_negative_scores: list[float]
    on_topic_topic_scores: list[float]
    on_topic_off_scores: list[float]
    off_topic_topic_scores: list[float]
    off_topic_off_scores: list[float]
    borderline_topic_scores: list[float]
    borderline_off_scores: list[float]


@dataclass
class GreetingThresholdResult:
    threshold: float
    tp: int
    fp: int
    fn: int
    tn: int


@dataclass
class OffTopicRelativeThresholdResult:
    off_topic_negative_min_similarity: float
    off_topic_margin_min_similarity: float
    tp: int
    fp: int
    fn: int
    tn: int


@dataclass
class OffTopicFallbackThresholdResult:
    off_topic_max_similarity: float
    tp: int
    fp: int
    fn: int
    tn: int


@dataclass
class ProviderCalibrationResult:
    provider_name: str
    model_id: str
    greeting: GreetingThresholdResult
    off_topic_relative: OffTopicRelativeThresholdResult
    off_topic_fallback: OffTopicFallbackThresholdResult

    def to_threshold_profile(self) -> dict[str, float]:
        return {
            "greeting_min_similarity": round(self.greeting.threshold, 3),
            "off_topic_max_similarity": round(self.off_topic_fallback.off_topic_max_similarity, 3),
            "off_topic_negative_min_similarity": round(
                self.off_topic_relative.off_topic_negative_min_similarity, 3
            ),
            "off_topic_margin_min_similarity": round(
                self.off_topic_relative.off_topic_margin_min_similarity, 3
            ),
        }


def _safe_float_round(value: float, places: int = 3) -> float:
    return float(round(float(value), places))


def _max_similarity(anchors: list[list[float]], vec: list[float]) -> float:
    mat = np.array(anchors)
    v = np.array(vec)
    norms = np.linalg.norm(mat, axis=1)
    v_norm = np.linalg.norm(v)
    if v_norm == 0:
        return 0.0
    sims = mat @ v / (norms * v_norm + 1e-10)
    return float(np.max(sims))


def _next_chunk(data: list[list[float]], start: int, length: int) -> tuple[list[list[float]], int]:
    return data[start : start + length], start + length


def _score_group(
    phrase_embeddings: list[list[float]],
    topic_anchors: list[list[float]],
    off_topic_anchors: list[list[float]],
) -> tuple[list[float], list[float]]:
    topic_scores: list[float] = []
    off_scores: list[float] = []
    for emb in phrase_embeddings:
        topic_scores.append(_max_similarity(topic_anchors, emb))
        off_scores.append(_max_similarity(off_topic_anchors, emb))
    return topic_scores, off_scores


def _linspace_candidates(start: float, stop: float, step: float) -> list[float]:
    values: list[float] = []
    current = start
    while current <= stop + 1e-9:
        values.append(round(current, 6))
        current += step
    return values


def _find_best_greeting_threshold(
    positive_scores: list[float],
    negative_scores: list[float],
) -> GreetingThresholdResult:
    # Precision-biased: minimise false positives first, then maximise true positives.
    candidates = _linspace_candidates(0.30, 0.99, 0.005)
    best: GreetingThresholdResult | None = None
    best_rank: tuple[int, int, float] | None = None
    for threshold in candidates:
        tp = sum(score >= threshold for score in positive_scores)
        fp = sum(score >= threshold for score in negative_scores)
        fn = len(positive_scores) - tp
        tn = len(negative_scores) - fp
        rank = (fp, -tp, -threshold)
        if best_rank is None or rank < best_rank:
            best_rank = rank
            best = GreetingThresholdResult(
                threshold=threshold,
                tp=tp,
                fp=fp,
                fn=fn,
                tn=tn,
            )
    assert best is not None
    return best


def _eval_off_topic_relative(
    *,
    on_topic_topic_scores: list[float],
    on_topic_off_scores: list[float],
    off_topic_topic_scores: list[float],
    off_topic_off_scores: list[float],
    borderline_topic_scores: list[float],
    borderline_off_scores: list[float],
    off_min: float,
    margin_min: float,
) -> OffTopicRelativeThresholdResult:
    tp = 0
    fp = 0
    for topic_score, off_score in zip(off_topic_topic_scores, off_topic_off_scores):
        if off_score >= off_min and (off_score - topic_score) >= margin_min:
            tp += 1
    for topic_score, off_score in zip(
        on_topic_topic_scores + borderline_topic_scores,
        on_topic_off_scores + borderline_off_scores,
    ):
        if off_score >= off_min and (off_score - topic_score) >= margin_min:
            fp += 1
    total_pos = len(off_topic_topic_scores)
    total_neg = len(on_topic_topic_scores) + len(borderline_topic_scores)
    return OffTopicRelativeThresholdResult(
        off_topic_negative_min_similarity=off_min,
        off_topic_margin_min_similarity=margin_min,
        tp=tp,
        fp=fp,
        fn=total_pos - tp,
        tn=total_neg - fp,
    )


def _find_best_off_topic_relative_thresholds(
    data: ProviderCalibrationInput,
) -> OffTopicRelativeThresholdResult:
    all_off_scores = (
        data.on_topic_off_scores
        + data.off_topic_off_scores
        + data.borderline_off_scores
    )
    all_margins = [
        off - topic
        for topic, off in zip(data.on_topic_topic_scores, data.on_topic_off_scores)
    ] + [
        off - topic
        for topic, off in zip(data.off_topic_topic_scores, data.off_topic_off_scores)
    ] + [
        off - topic
        for topic, off in zip(data.borderline_topic_scores, data.borderline_off_scores)
    ]
    off_min_start = max(0.30, min(all_off_scores) - 0.05)
    off_min_stop = min(0.99, max(all_off_scores) + 0.02)
    margin_start = min(-0.25, min(all_margins) - 0.05)
    margin_stop = max(0.25, max(all_margins) + 0.05)

    off_min_candidates = _linspace_candidates(off_min_start, off_min_stop, 0.005)
    margin_candidates = _linspace_candidates(margin_start, margin_stop, 0.005)

    best: OffTopicRelativeThresholdResult | None = None
    best_rank: tuple[int, int, int, float, float] | None = None
    for off_min in off_min_candidates:
        for margin_min in margin_candidates:
            result = _eval_off_topic_relative(
                on_topic_topic_scores=data.on_topic_topic_scores,
                on_topic_off_scores=data.on_topic_off_scores,
                off_topic_topic_scores=data.off_topic_topic_scores,
                off_topic_off_scores=data.off_topic_off_scores,
                borderline_topic_scores=data.borderline_topic_scores,
                borderline_off_scores=data.borderline_off_scores,
                off_min=off_min,
                margin_min=margin_min,
            )
            # Precision-biased (FP first), then recall, then stricter thresholds.
            rank = (
                result.fp,
                result.fn,
                -result.tp,
                -off_min,
                -margin_min,
            )
            if best_rank is None or rank < best_rank:
                best_rank = rank
                best = result
    assert best is not None
    return best


def _find_best_off_topic_fallback_threshold(
    data: ProviderCalibrationInput,
) -> OffTopicFallbackThresholdResult:
    topic_scores_all = (
        data.on_topic_topic_scores
        + data.off_topic_topic_scores
        + data.borderline_topic_scores
    )
    candidates = _linspace_candidates(
        max(0.05, min(topic_scores_all) - 0.05),
        min(0.99, max(topic_scores_all) + 0.02),
        0.005,
    )
    best: OffTopicFallbackThresholdResult | None = None
    best_rank: tuple[int, int, int, float] | None = None
    for threshold in candidates:
        tp = sum(score < threshold for score in data.off_topic_topic_scores)
        fp = sum(score < threshold for score in (data.on_topic_topic_scores + data.borderline_topic_scores))
        fn = len(data.off_topic_topic_scores) - tp
        tn = len(data.on_topic_topic_scores) + len(data.borderline_topic_scores) - fp
        rank = (fp, fn, -tp, -threshold)
        if best_rank is None or rank < best_rank:
            best_rank = rank
            best = OffTopicFallbackThresholdResult(
                off_topic_max_similarity=threshold,
                tp=tp,
                fp=fp,
                fn=fn,
                tn=tn,
            )
    assert best is not None
    return best


def _build_provider_calibration_input(
    provider_name: str,
    model_id: str,
    *,
    greeting_anchor_embeddings: list[list[float]],
    topic_anchor_embeddings: list[list[float]],
    off_topic_anchor_embeddings: list[list[float]],
    phrase_embeddings: list[list[float]],
) -> ProviderCalibrationInput:
    idx = 0
    greeting_true_embs, idx = _next_chunk(phrase_embeddings, idx, len(GREETING_TRUE))
    greeting_false_embs, idx = _next_chunk(phrase_embeddings, idx, len(GREETING_FALSE_POSITIVES))
    greeting_question_embs, idx = _next_chunk(phrase_embeddings, idx, len(GREETING_WITH_QUESTION))
    on_topic_embs, idx = _next_chunk(phrase_embeddings, idx, len(ON_TOPIC))
    off_topic_embs, idx = _next_chunk(phrase_embeddings, idx, len(OFF_TOPIC))
    borderline_embs, idx = _next_chunk(phrase_embeddings, idx, len(BORDERLINE))
    _ = idx

    greeting_true_scores = [_max_similarity(greeting_anchor_embeddings, emb) for emb in greeting_true_embs]
    greeting_false_scores = [_max_similarity(greeting_anchor_embeddings, emb) for emb in greeting_false_embs]
    greeting_question_scores = [_max_similarity(greeting_anchor_embeddings, emb) for emb in greeting_question_embs]

    on_topic_topic_scores, on_topic_off_scores = _score_group(
        on_topic_embs,
        topic_anchor_embeddings,
        off_topic_anchor_embeddings,
    )
    off_topic_topic_scores, off_topic_off_scores = _score_group(
        off_topic_embs,
        topic_anchor_embeddings,
        off_topic_anchor_embeddings,
    )
    borderline_topic_scores, borderline_off_scores = _score_group(
        borderline_embs,
        topic_anchor_embeddings,
        off_topic_anchor_embeddings,
    )

    return ProviderCalibrationInput(
        provider_name=provider_name,
        model_id=model_id,
        greeting_true_scores=greeting_true_scores,
        greeting_negative_scores=greeting_false_scores + greeting_question_scores,
        on_topic_topic_scores=on_topic_topic_scores,
        on_topic_off_scores=on_topic_off_scores,
        off_topic_topic_scores=off_topic_topic_scores,
        off_topic_off_scores=off_topic_off_scores,
        borderline_topic_scores=borderline_topic_scores,
        borderline_off_scores=borderline_off_scores,
    )


async def _embed_calibration_corpus(service: Any) -> tuple[list[list[float]], list[list[float]]]:
    anchor_texts = GREETING_ANCHORS + TOPIC_ANCHORS + OFF_TOPIC_ANCHORS
    phrase_texts = (
        GREETING_TRUE
        + GREETING_FALSE_POSITIVES
        + GREETING_WITH_QUESTION
        + ON_TOPIC
        + OFF_TOPIC
        + BORDERLINE
    )
    anchor_embeddings = await service.embed_batch(anchor_texts)
    phrase_embeddings = await service.embed_batch(phrase_texts)
    return anchor_embeddings, phrase_embeddings


def _split_anchor_embeddings(
    all_anchor_embeddings: list[list[float]],
) -> tuple[list[list[float]], list[list[float]], list[list[float]]]:
    n_greetings = len(GREETING_ANCHORS)
    n_topics = len(TOPIC_ANCHORS)
    greeting_embs = all_anchor_embeddings[:n_greetings]
    topic_embs = all_anchor_embeddings[n_greetings : n_greetings + n_topics]
    off_topic_embs = all_anchor_embeddings[n_greetings + n_topics :]
    return greeting_embs, topic_embs, off_topic_embs


def _summarise_scores(name: str, scores: list[float]) -> str:
    if not scores:
        return f"{name}: no samples"
    return (
        f"{name}: min={min(scores):.3f} max={max(scores):.3f} "
        f"avg={sum(scores)/len(scores):.3f}"
    )


def _print_provider_report(result: ProviderCalibrationResult, data: ProviderCalibrationInput) -> None:
    rel = result.off_topic_relative
    fb = result.off_topic_fallback
    print("=" * 72)
    print(f"{result.provider_name} ({result.model_id})")
    print("=" * 72)
    print(_summarise_scores("Greeting true", data.greeting_true_scores))
    print(_summarise_scores("Greeting negatives", data.greeting_negative_scores))
    print(
        "Greeting threshold search (precision-biased): "
        f"threshold={result.greeting.threshold:.3f} "
        f"(TP={result.greeting.tp}, FP={result.greeting.fp}, "
        f"FN={result.greeting.fn}, TN={result.greeting.tn})"
    )
    print()
    print("Off-topic relative rule search (precision-biased):")
    print(
        f"  off_topic_negative_min_similarity={rel.off_topic_negative_min_similarity:.3f}, "
        f"off_topic_margin_min_similarity={rel.off_topic_margin_min_similarity:.3f} "
        f"(TP={rel.tp}, FP={rel.fp}, FN={rel.fn}, TN={rel.tn})"
    )
    print("Off-topic fallback topic-only rule (kept as backup in profile):")
    print(
        f"  off_topic_max_similarity={fb.off_topic_max_similarity:.3f} "
        f"(TP={fb.tp}, FP={fb.fp}, FN={fb.fn}, TN={fb.tn})"
    )
    print()
    print("Recommended profile (copy to EMBEDDING_THRESHOLDS):")
    print(json.dumps(result.to_threshold_profile(), ensure_ascii=True, sort_keys=True))
    print()


def _build_provider_specs() -> list[tuple[str, str, callable]]:
    repo_root = Path(__file__).resolve().parents[2]
    creds_candidates = [
        (settings.google_application_credentials or "").strip(),
        os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_HOST_PATH", "").strip(),
        (settings.google_application_credentials_host_path or "").strip(),
        str(repo_root / "ai-coding-tutor-488300-8641d2e48a27.json"),
    ]
    creds_path = next((p for p in creds_candidates if p and Path(p).exists()), "")

    specs: list[tuple[str, str, callable]] = []

    if settings.cohere_api_key:
        specs.append(
            (
                "cohere",
                settings.embedding_model_cohere,
                lambda: CohereEmbeddingService(
                    settings.cohere_api_key,
                    model_id=settings.embedding_model_cohere,
                ),
            )
        )

    if creds_path:
        specs.append(
            (
                "vertex",
                settings.embedding_model_vertex,
                lambda: VertexEmbeddingService(
                    token_provider=GoogleServiceAccountTokenProvider(creds_path),
                    project_id=resolve_google_project_id(creds_path, settings.google_cloud_project_id),
                    location=settings.google_vertex_embedding_location,
                    model_id=settings.embedding_model_vertex,
                    dimension=256,
                ),
            )
        )

    if settings.voyageai_api_key:
        specs.append(
            (
                "voyage",
                settings.embedding_model_voyage,
                lambda: VoyageEmbeddingService(
                    settings.voyageai_api_key,
                    model_id=settings.embedding_model_voyage,
                ),
            )
        )

    return specs


async def _calibrate_provider(
    provider_name: str,
    model_id: str,
    service_factory,
) -> ProviderCalibrationResult:
    service = service_factory()
    try:
        all_anchor_embeddings, phrase_embeddings = await _embed_calibration_corpus(service)
        greeting_anchor_embeddings, topic_anchor_embeddings, off_topic_anchor_embeddings = (
            _split_anchor_embeddings(all_anchor_embeddings)
        )
        data = _build_provider_calibration_input(
            provider_name,
            model_id,
            greeting_anchor_embeddings=greeting_anchor_embeddings,
            topic_anchor_embeddings=topic_anchor_embeddings,
            off_topic_anchor_embeddings=off_topic_anchor_embeddings,
            phrase_embeddings=phrase_embeddings,
        )
        greeting = _find_best_greeting_threshold(
            data.greeting_true_scores,
            data.greeting_negative_scores,
        )
        off_topic_relative = _find_best_off_topic_relative_thresholds(data)
        off_topic_fallback = _find_best_off_topic_fallback_threshold(data)
        result = ProviderCalibrationResult(
            provider_name=provider_name,
            model_id=model_id,
            greeting=greeting,
            off_topic_relative=off_topic_relative,
            off_topic_fallback=off_topic_fallback,
        )
        _print_provider_report(result, data)
        return result
    finally:
        await service.close()


async def main() -> None:
    print("=== Semantic Filter Threshold Calibration (Cohere, Vertex AI, Voyage AI) ===")
    print("Filters are optional and disabled by default. This script calibrates provider-specific profiles.")
    print()

    provider_specs = _build_provider_specs()
    if not provider_specs:
        print("ERROR: No embedding provider credentials available for calibration")
        sys.exit(1)

    results: list[ProviderCalibrationResult] = []
    for provider_name, model_id, service_factory in provider_specs:
        try:
            results.append(await _calibrate_provider(provider_name, model_id, service_factory))
        except Exception as exc:
            print(f"[SKIP] {provider_name}: calibration failed: {exc}")
            print()

    if not results:
        print("ERROR: No provider calibration completed successfully")
        sys.exit(2)

    print("=" * 72)
    print("Current code thresholds")
    print("=" * 72)
    for provider_name in ("cohere", "vertex", "voyage"):
        profile = EMBEDDING_THRESHOLDS.get(provider_name)
        if profile is None:
            continue
        print(f"{provider_name}: {json.dumps(profile, ensure_ascii=True, sort_keys=True)}")
    print()

    print("=" * 72)
    print("Recommended thresholds from this run")
    print("=" * 72)
    recommended = {
        result.provider_name: result.to_threshold_profile()
        for result in results
    }
    print(json.dumps(recommended, ensure_ascii=True, sort_keys=True, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
