"""Select and return the configured LLM provider with automatic fallback."""

import logging

from app.ai.llm_base import LLMProvider, LLMError
from app.ai.llm_anthropic import AnthropicProvider
from app.ai.llm_openai import OpenAIProvider
from app.ai.llm_google import GoogleGeminiProvider

logger = logging.getLogger(__name__)


def get_llm_provider(settings) -> LLMProvider:
    """Return the configured primary LLM provider, falling back to any available one."""
    provider = settings.llm_provider.lower()

    if provider == "anthropic" and settings.anthropic_api_key:
        return AnthropicProvider(settings.anthropic_api_key)
    if provider == "openai" and settings.openai_api_key:
        return OpenAIProvider(settings.openai_api_key)
    if provider == "google" and settings.google_api_key:
        return GoogleGeminiProvider(settings.google_api_key)

    # Fall back to any available provider.
    if settings.anthropic_api_key:
        return AnthropicProvider(settings.anthropic_api_key)
    if settings.openai_api_key:
        return OpenAIProvider(settings.openai_api_key)
    if settings.google_api_key:
        return GoogleGeminiProvider(settings.google_api_key)

    raise LLMError(
        "No LLM provider configured. "
        "Set ANTHROPIC_API_KEY, OPENAI_API_KEY, or GOOGLE_API_KEY in .env"
    )
