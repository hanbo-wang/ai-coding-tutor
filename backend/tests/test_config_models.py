"""Model registry and alias normalisation tests."""

import pytest

from app.ai.model_registry import (
    normalise_embedding_provider,
    normalise_llm_provider,
    normalise_model_alias,
    validate_supported_embedding_model,
    validate_supported_llm_model,
)


def test_normalise_model_alias_maps_user_friendly_names() -> None:
    assert normalise_model_alias("GPT-5 mini") == "gpt-5-mini"
    assert normalise_model_alias("Claude Sonnet 4.6") == "claude-sonnet-4-6"
    assert normalise_model_alias("gemini 3 pro preview") == "gemini-3.1-pro-preview"


def test_provider_aliases_normalise_to_internal_ids() -> None:
    assert normalise_llm_provider("gemini") == "google"
    assert normalise_llm_provider("claude") == "anthropic"
    assert normalise_embedding_provider("google") == "vertex"
    assert normalise_embedding_provider("voyageai") == "voyage"


def test_validate_supported_models_accepts_known_values() -> None:
    assert validate_supported_llm_model("openai", "GPT-5 mini") == "gpt-5-mini"
    assert (
        validate_supported_embedding_model("vertex", "multimodalembedding@001")
        == "multimodalembedding@001"
    )


def test_validate_supported_models_rejects_unknown_values() -> None:
    with pytest.raises(ValueError):
        validate_supported_llm_model("openai", "gpt-unknown")
