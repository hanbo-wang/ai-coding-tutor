"""Select and return the configured LLM provider with automatic fallback."""

import logging

from app.ai.google_auth import (
    GoogleServiceAccountTokenProvider,
    resolve_google_credentials_path,
    resolve_google_project_id,
)
from app.ai.llm_base import LLMProvider, LLMError
from app.ai.llm_anthropic import AnthropicProvider
from app.ai.llm_openai import OpenAIProvider
from app.ai.llm_google import GoogleGeminiAIStudioProvider, GoogleGeminiProvider
from app.ai.model_registry import validate_supported_llm_model

logger = logging.getLogger(__name__)


def _normalise_google_transport(value: str) -> str:
    transport = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "aistudio": "aistudio",
        "ai_studio": "aistudio",
        "studio": "aistudio",
        "vertex": "vertex",
        "vertex_ai": "vertex",
    }
    return aliases.get(transport, transport)


def _build_anthropic_provider(settings) -> AnthropicProvider:
    model_id = validate_supported_llm_model("anthropic", settings.llm_model_anthropic)
    return AnthropicProvider(settings.anthropic_api_key, model_id=model_id)


def _build_openai_provider(settings) -> OpenAIProvider:
    model_id = validate_supported_llm_model("openai", settings.llm_model_openai)
    return OpenAIProvider(settings.openai_api_key, model_id=model_id)


def _build_google_provider(settings) -> LLMProvider:
    model_id = validate_supported_llm_model("google", settings.llm_model_google)
    transport = _normalise_google_transport(getattr(settings, "google_gemini_transport", ""))
    if transport == "aistudio":
        if not settings.google_api_key:
            raise LLMError(
                "GOOGLE_GEMINI_TRANSPORT is set to 'aistudio' but GOOGLE_API_KEY is empty"
            )
        return GoogleGeminiAIStudioProvider(settings.google_api_key, model_id=model_id)
    if transport != "vertex":
        raise LLMError(
            "Invalid GOOGLE_GEMINI_TRANSPORT. Use 'aistudio' or 'vertex' for the google provider"
        )
    credentials_path = resolve_google_credentials_path(
        settings.google_application_credentials,
        getattr(settings, "google_application_credentials_host_path", ""),
    )
    token_provider = GoogleServiceAccountTokenProvider(credentials_path)
    project_id = resolve_google_project_id(
        credentials_path,
        settings.google_cloud_project_id,
    )
    return GoogleGeminiProvider(
        token_provider=token_provider,
        project_id=project_id,
        location=settings.google_vertex_gemini_location,
        model_id=model_id,
    )


def _can_use_google(settings) -> bool:
    transport = _normalise_google_transport(getattr(settings, "google_gemini_transport", ""))
    if transport == "aistudio":
        return bool(getattr(settings, "google_api_key", ""))
    if transport == "vertex":
        return bool(
            getattr(settings, "google_application_credentials", "")
            or getattr(settings, "google_application_credentials_host_path", "")
        )
    return False


def _google_setup_hint() -> str:
    return (
        "GOOGLE_GEMINI_TRANSPORT (`aistudio` or `vertex`) and the matching Google "
        "credentials: GOOGLE_API_KEY for AI Studio, or GOOGLE_APPLICATION_CREDENTIALS "
        "(Vertex AI service account JSON path)"
    )


def get_llm_provider(settings) -> LLMProvider:
    """Return the configured primary LLM provider, falling back to any available one."""
    provider = settings.llm_provider.lower()

    if provider == "anthropic" and settings.anthropic_api_key:
        try:
            return _build_anthropic_provider(settings)
        except Exception as exc:
            logger.warning("Configured Anthropic provider unavailable, trying fallbacks: %s", exc)
    if provider == "openai" and settings.openai_api_key:
        try:
            return _build_openai_provider(settings)
        except Exception as exc:
            logger.warning("Configured OpenAI provider unavailable, trying fallbacks: %s", exc)
    if provider == "google" and _can_use_google(settings):
        try:
            return _build_google_provider(settings)
        except Exception as exc:
            logger.warning("Configured Google provider unavailable, trying fallbacks: %s", exc)

    # Fall back to any available provider.
    if settings.anthropic_api_key:
        try:
            return _build_anthropic_provider(settings)
        except Exception as exc:
            logger.warning("Anthropic fallback unavailable: %s", exc)
    if settings.openai_api_key:
        try:
            return _build_openai_provider(settings)
        except Exception as exc:
            logger.warning("OpenAI fallback unavailable: %s", exc)
    if _can_use_google(settings):
        try:
            return _build_google_provider(settings)
        except Exception as exc:
            logger.warning("Google fallback unavailable: %s", exc)

    raise LLMError(
        "No LLM provider configured. "
        f"Set ANTHROPIC_API_KEY, OPENAI_API_KEY, or {_google_setup_hint()} in .env"
    )
