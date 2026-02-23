"""Model registry and alias normalisation for supported providers."""

from __future__ import annotations

import re


SUPPORTED_LLM_MODELS: dict[str, set[str]] = {
    "google": {
        "gemini-3-flash-preview",
        "gemini-3.1-pro-preview",
    },
    "anthropic": {
        "claude-sonnet-4-6",
        "claude-haiku-4-5",
    },
    "openai": {
        "gpt-5.2",
        "gpt-5-mini",
    },
}

SUPPORTED_EMBEDDING_MODELS: dict[str, set[str]] = {
    "vertex": {"multimodalembedding@001"},
    "cohere": {"embed-v4.0"},
    "voyage": {"voyage-multimodal-3.5"},
}


_MODEL_ALIASES = {
    # OpenAI
    "gpt-5 mini": "gpt-5-mini",
    "gpt5 mini": "gpt-5-mini",
    "gpt 5 mini": "gpt-5-mini",
    "gpt-5.2": "gpt-5.2",
    "gpt 5.2": "gpt-5.2",
    # Anthropic
    "claude sonnet 4.6": "claude-sonnet-4-6",
    "claude-sonnet-4.6": "claude-sonnet-4-6",
    "claude sonnet 4-6": "claude-sonnet-4-6",
    "claude haiku 4.5": "claude-haiku-4-5",
    "claude-haiku-4.5": "claude-haiku-4-5",
    "claude haiku 4-5": "claude-haiku-4-5",
    # Google
    "gemini-3-flash-preview": "gemini-3-flash-preview",
    "gemini 3 flash preview": "gemini-3-flash-preview",
    "gemini-3.1-pro-preview": "gemini-3.1-pro-preview",
    "gemini 3.1 pro preview": "gemini-3.1-pro-preview",
    "gemini-3-pro-preview": "gemini-3.1-pro-preview",
    "gemini 3 pro preview": "gemini-3.1-pro-preview",
    # Embeddings
    "multimodalembedding@001": "multimodalembedding@001",
    "vertex multimodalembedding@001": "multimodalembedding@001",
}


def _canonicalise_key(value: str) -> str:
    normalised = value.strip().lower()
    normalised = re.sub(r"\s+", " ", normalised)
    return normalised


def normalise_model_alias(value: str) -> str:
    """Map user-friendly model labels to API model IDs."""
    key = _canonicalise_key(value)
    if key in _MODEL_ALIASES:
        return _MODEL_ALIASES[key]
    # Fallback: normalise spacing and casing but preserve punctuation.
    return key.replace(" ", "-")


def normalise_llm_provider(value: str) -> str:
    provider = value.strip().lower()
    aliases = {
        "vertex": "google",
        "gemini": "google",
        "vertexai": "google",
        "anthropic": "anthropic",
        "claude": "anthropic",
        "openai": "openai",
    }
    return aliases.get(provider, provider)


def normalise_embedding_provider(value: str) -> str:
    provider = value.strip().lower()
    aliases = {
        "vertex": "vertex",
        "google": "vertex",
        "vertexai": "vertex",
        "cohere": "cohere",
        "voyage": "voyage",
        "voyageai": "voyage",
    }
    return aliases.get(provider, provider)


def validate_supported_llm_model(provider: str, model_id: str) -> str:
    """Return the canonical model ID or raise ValueError."""
    canonical_provider = normalise_llm_provider(provider)
    canonical_model = normalise_model_alias(model_id)
    supported = SUPPORTED_LLM_MODELS.get(canonical_provider, set())
    if canonical_model not in supported:
        raise ValueError(
            f"Unsupported LLM model '{model_id}' for provider '{provider}'. "
            f"Supported models: {sorted(supported)}"
        )
    return canonical_model


def validate_supported_embedding_model(provider: str, model_id: str) -> str:
    """Return the canonical embedding model ID or raise ValueError."""
    canonical_provider = normalise_embedding_provider(provider)
    canonical_model = normalise_model_alias(model_id)
    supported = SUPPORTED_EMBEDDING_MODELS.get(canonical_provider, set())
    if canonical_model not in supported:
        raise ValueError(
            f"Unsupported embedding model '{model_id}' for provider '{provider}'. "
            f"Supported models: {sorted(supported)}"
        )
    return canonical_model
