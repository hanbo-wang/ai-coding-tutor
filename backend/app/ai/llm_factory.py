"""Select and build LLM providers with explicit fallback candidates."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.ai.google_auth import (
    GoogleServiceAccountTokenProvider,
    resolve_google_credentials_path,
    resolve_google_project_id,
)
from app.ai.llm_anthropic import AnthropicProvider
from app.ai.llm_base import LLMError, LLMProvider
from app.ai.llm_google import GoogleGeminiAIStudioProvider, GoogleGeminiProvider
from app.ai.llm_openai import OpenAIProvider
from app.ai.model_registry import (
    SUPPORTED_LLM_MODELS,
    normalise_google_vertex_location,
    normalise_llm_provider,
    validate_supported_llm_model,
)
from app.ai.pricing import get_model_pricing

logger = logging.getLogger(__name__)

PROVIDER_RING: tuple[str, ...] = ("anthropic", "openai", "google")


@dataclass(frozen=True)
class LLMTarget:
    """Concrete runtime target for one provider/model/(transport) combination."""

    provider: str
    model_id: str
    google_transport: str | None = None


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


def _model_sort_key(provider: str, model_id: str) -> tuple[float, str]:
    pricing = get_model_pricing(provider, model_id)
    # Smaller total list-price first, then deterministic lexical tiebreak.
    total = float(pricing.get("input_per_mtok", 0.0)) + float(
        pricing.get("output_per_mtok", 0.0)
    )
    return (total, model_id)


def _ordered_models(provider: str) -> list[str]:
    canonical_provider = normalise_llm_provider(provider)
    models = SUPPORTED_LLM_MODELS.get(canonical_provider, set())
    return sorted(models, key=lambda model_id: _model_sort_key(canonical_provider, model_id))


def _configured_model_for_provider(settings, provider: str) -> str:
    canonical_provider = normalise_llm_provider(provider)
    if canonical_provider == "anthropic":
        return str(getattr(settings, "llm_model_anthropic", "") or "")
    if canonical_provider == "openai":
        return str(getattr(settings, "llm_model_openai", "") or "")
    if canonical_provider == "google":
        return str(getattr(settings, "llm_model_google", "") or "")
    return ""


def _google_transport_has_credentials(settings, transport: str) -> bool:
    canonical_transport = _normalise_google_transport(transport)
    if canonical_transport == "aistudio":
        return bool(getattr(settings, "google_api_key", ""))
    if canonical_transport == "vertex":
        return bool(
            getattr(settings, "google_application_credentials", "")
            or getattr(settings, "google_application_credentials_host_path", "")
        )
    return False


def _available_google_transports(
    settings,
    preferred_transport: str | None = None,
) -> list[str]:
    preferred = _normalise_google_transport(
        preferred_transport or getattr(settings, "google_gemini_transport", "")
    )
    ordered = [preferred] if preferred else []
    for candidate in ("aistudio", "vertex"):
        if candidate not in ordered:
            ordered.append(candidate)
    return [
        transport
        for transport in ordered
        if _google_transport_has_credentials(settings, transport)
    ]


def _has_provider_credentials(settings, provider: str) -> bool:
    canonical_provider = normalise_llm_provider(provider)
    if canonical_provider == "anthropic":
        return bool(getattr(settings, "anthropic_api_key", ""))
    if canonical_provider == "openai":
        return bool(getattr(settings, "openai_api_key", ""))
    if canonical_provider == "google":
        return bool(_available_google_transports(settings))
    return False


def _build_anthropic_provider(settings, *, model_id: str) -> AnthropicProvider:
    api_key = str(getattr(settings, "anthropic_api_key", "") or "")
    if not api_key:
        raise LLMError("ANTHROPIC_API_KEY is empty")
    canonical_model = validate_supported_llm_model("anthropic", model_id)
    return AnthropicProvider(api_key, model_id=canonical_model)


def _build_openai_provider(settings, *, model_id: str) -> OpenAIProvider:
    api_key = str(getattr(settings, "openai_api_key", "") or "")
    if not api_key:
        raise LLMError("OPENAI_API_KEY is empty")
    canonical_model = validate_supported_llm_model("openai", model_id)
    return OpenAIProvider(api_key, model_id=canonical_model)


def _build_google_provider(
    settings,
    *,
    model_id: str,
    transport: str,
) -> LLMProvider:
    canonical_model = validate_supported_llm_model("google", model_id)
    canonical_transport = _normalise_google_transport(transport)
    if canonical_transport == "aistudio":
        api_key = str(getattr(settings, "google_api_key", "") or "")
        if not api_key:
            raise LLMError(
                "Google AI Studio transport requested but GOOGLE_API_KEY is empty"
            )
        return GoogleGeminiAIStudioProvider(api_key, model_id=canonical_model)
    if canonical_transport != "vertex":
        raise LLMError(
            "Invalid Google transport. Use 'aistudio' or 'vertex' for the google provider"
        )
    credentials_path = resolve_google_credentials_path(
        getattr(settings, "google_application_credentials", ""),
        getattr(settings, "google_application_credentials_host_path", ""),
    )
    token_provider = GoogleServiceAccountTokenProvider(credentials_path)
    project_id = resolve_google_project_id(
        credentials_path,
        getattr(settings, "google_cloud_project_id", ""),
    )
    configured_location = str(getattr(settings, "google_vertex_gemini_location", "") or "")
    location = normalise_google_vertex_location(configured_location, canonical_model)
    if location != configured_location.strip().lower():
        logger.info(
            "Google Vertex location normalised from '%s' to '%s' for model '%s'",
            configured_location,
            location,
            canonical_model,
        )
    return GoogleGeminiProvider(
        token_provider=token_provider,
        project_id=project_id,
        location=location,
        model_id=canonical_model,
    )


def build_llm_provider_for_target(settings, target: LLMTarget) -> LLMProvider:
    """Build a provider instance for an explicit runtime target."""

    provider = normalise_llm_provider(target.provider)
    if provider == "anthropic":
        return _build_anthropic_provider(settings, model_id=target.model_id)
    if provider == "openai":
        return _build_openai_provider(settings, model_id=target.model_id)
    if provider == "google":
        transport = _normalise_google_transport(
            target.google_transport or getattr(settings, "google_gemini_transport", "")
        )
        if transport not in {"aistudio", "vertex"}:
            raise LLMError(
                "Invalid GOOGLE_GEMINI_TRANSPORT. Use 'aistudio' or 'vertex' for the google provider"
            )
        return _build_google_provider(
            settings,
            model_id=target.model_id,
            transport=transport,
        )
    raise LLMError(f"Unsupported LLM provider '{target.provider}'")


def build_llm_provider(
    settings,
    *,
    provider: str,
    model_id: str,
    google_transport: str | None = None,
) -> LLMProvider:
    """Build a provider instance from explicit provider/model/(transport)."""

    return build_llm_provider_for_target(
        settings,
        LLMTarget(
            provider=normalise_llm_provider(provider),
            model_id=model_id,
            google_transport=google_transport,
        ),
    )


def list_llm_fallback_targets(
    settings,
    *,
    current_provider: str,
    current_model: str,
    current_google_transport: str | None = None,
) -> list[LLMTarget]:
    """Return ordered fallback targets for one chat session.

    Order policy:
    1. Same provider, other supported models (small model first).
    2. Cross-provider ring order: anthropic -> openai -> google -> anthropic
       (starting from the provider after the current provider).
    3. Google targets keep current transport first and only include alternate
       transport when matching credentials exist.
    """

    provider = normalise_llm_provider(current_provider)
    if provider not in PROVIDER_RING:
        return []

    try:
        model = validate_supported_llm_model(provider, current_model)
    except ValueError:
        model = _configured_model_for_provider(settings, provider)
        if model:
            model = validate_supported_llm_model(provider, model)
        else:
            return []

    preferred_google_transport = _normalise_google_transport(
        current_google_transport or getattr(settings, "google_gemini_transport", "")
    )
    candidates: list[LLMTarget] = []
    seen: set[tuple[str, str, str]] = {(provider, model, preferred_google_transport)}

    def _add_candidate(
        candidate_provider: str,
        candidate_model: str,
        *,
        google_transport: str | None = None,
    ) -> None:
        canonical_provider = normalise_llm_provider(candidate_provider)
        if not _has_provider_credentials(settings, canonical_provider):
            return
        try:
            canonical_model = validate_supported_llm_model(canonical_provider, candidate_model)
        except ValueError:
            return
        canonical_transport = (
            _normalise_google_transport(google_transport)
            if canonical_provider == "google"
            else ""
        )
        if canonical_provider == "google":
            if not canonical_transport:
                return
            if not _google_transport_has_credentials(settings, canonical_transport):
                return
        key = (canonical_provider, canonical_model, canonical_transport)
        if key in seen:
            return
        seen.add(key)
        candidates.append(
            LLMTarget(
                provider=canonical_provider,
                model_id=canonical_model,
                google_transport=canonical_transport or None,
            )
        )

    # Same provider first (other models only).
    for same_provider_model in _ordered_models(provider):
        if same_provider_model == model:
            continue
        if provider == "google":
            for transport in _available_google_transports(
                settings, preferred_google_transport
            ):
                _add_candidate(
                    "google",
                    same_provider_model,
                    google_transport=transport,
                )
        else:
            _add_candidate(provider, same_provider_model)

    # Then cross-provider ring order.
    current_idx = PROVIDER_RING.index(provider)
    ring_after_current = [
        PROVIDER_RING[(current_idx + offset) % len(PROVIDER_RING)]
        for offset in range(1, len(PROVIDER_RING))
    ]
    for ring_provider in ring_after_current:
        for ring_model in _ordered_models(ring_provider):
            if ring_provider == "google":
                for transport in _available_google_transports(
                    settings, preferred_google_transport
                ):
                    _add_candidate(
                        "google",
                        ring_model,
                        google_transport=transport,
                    )
            else:
                _add_candidate(ring_provider, ring_model)

    return candidates


def _google_setup_hint() -> str:
    return (
        "GOOGLE_GEMINI_TRANSPORT (`aistudio` or `vertex`) and the matching Google "
        "credentials: GOOGLE_API_KEY for AI Studio, or GOOGLE_APPLICATION_CREDENTIALS "
        "(Vertex AI service account JSON path)"
    )


def get_llm_provider(settings) -> LLMProvider:
    """Return the current provider and fall back to available alternatives."""

    configured_provider = normalise_llm_provider(str(getattr(settings, "llm_provider", "") or ""))
    if configured_provider not in PROVIDER_RING:
        configured_provider = "google"

    configured_model = _configured_model_for_provider(settings, configured_provider)
    if not configured_model:
        configured_model = _ordered_models(configured_provider)[0]

    configured_transport = (
        _normalise_google_transport(getattr(settings, "google_gemini_transport", ""))
        if configured_provider == "google"
        else None
    )

    primary_target = LLMTarget(
        provider=configured_provider,
        model_id=configured_model,
        google_transport=configured_transport,
    )
    targets = [primary_target] + list_llm_fallback_targets(
        settings,
        current_provider=primary_target.provider,
        current_model=primary_target.model_id,
        current_google_transport=primary_target.google_transport,
    )

    for idx, target in enumerate(targets):
        try:
            return build_llm_provider_for_target(settings, target)
        except Exception as exc:
            if idx == 0:
                logger.warning(
                    "Primary provider unavailable (%s/%s): %s",
                    target.provider,
                    target.model_id,
                    exc,
                )
            else:
                logger.warning(
                    "Fallback unavailable (%s/%s): %s",
                    target.provider,
                    target.model_id,
                    exc,
                )

    raise LLMError(
        "No LLM provider is available. "
        f"Set ANTHROPIC_API_KEY, OPENAI_API_KEY, or {_google_setup_hint()} in .env"
    )
