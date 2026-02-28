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

GLOBAL_ONLY_GOOGLE_VERTEX_MODELS: set[str] = {
    "gemini-3-flash-preview",
    "gemini-3.1-pro-preview",
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
        "google-aistudio": "google",
        "google-ai-studio": "google",
        "google-vertex": "google",
        "google-vertex-ai": "google",
        "anthropic": "anthropic",
        "claude": "anthropic",
        "openai": "openai",
    }
    return aliases.get(provider, provider)


def normalise_google_vertex_location(location: str, model_id: str = "") -> str:
    """Normalise Vertex location, using `global` for known global-only models."""
    normalised = str(location or "").strip().lower() or "global"
    canonical_model = normalise_model_alias(model_id) if str(model_id or "").strip() else ""
    if canonical_model in GLOBAL_ONLY_GOOGLE_VERTEX_MODELS:
        return "global"
    return normalised


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
