"""Model registry and alias normalisation tests."""

import pytest

from app.ai.model_registry import (
    normalise_google_vertex_location,
    normalise_llm_provider,
    normalise_model_alias,
    validate_supported_llm_model,
)


def test_normalise_model_alias_maps_user_friendly_names() -> None:
    assert normalise_model_alias("GPT-5 mini") == "gpt-5-mini"
    assert normalise_model_alias("Claude Sonnet 4.6") == "claude-sonnet-4-6"
    assert normalise_model_alias("gemini 3 pro preview") == "gemini-3.1-pro-preview"


def test_provider_aliases_normalise_to_internal_ids() -> None:
    assert normalise_llm_provider("gemini") == "google"
    assert normalise_llm_provider("claude") == "anthropic"
    assert normalise_llm_provider("google-ai-studio") == "google"
    assert normalise_llm_provider("google-vertex") == "google"


def test_validate_supported_models_accepts_known_values() -> None:
    assert validate_supported_llm_model("openai", "GPT-5 mini") == "gpt-5-mini"


def test_validate_supported_models_rejects_unknown_values() -> None:
    with pytest.raises(ValueError):
        validate_supported_llm_model("openai", "gpt-unknown")


def test_google_vertex_location_normalisation_for_global_only_models() -> None:
    assert normalise_google_vertex_location("europe-west2", "gemini-3-flash-preview") == "global"
    assert normalise_google_vertex_location("", "gemini-3.1-pro-preview") == "global"
    assert normalise_google_vertex_location("europe-west2", "unknown-model") == "europe-west2"
