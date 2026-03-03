"""Health check endpoints for provider verification and model smoke tests."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter

from app.ai.verify_keys import smoke_test_supported_models, verify_all_keys
from app.config import settings
from app.ai.model_registry import normalise_llm_provider

router = APIRouter(prefix="/api/health", tags=["health"])
AI_HEALTH_CACHE_TTL = timedelta(seconds=30)
_last_ai_health_result: dict[str, bool] | None = None
_last_ai_health_at: datetime | None = None
AI_MODEL_HEALTH_CACHE_TTL = timedelta(seconds=60)
_last_ai_models_result: dict | None = None
_last_ai_models_at: datetime | None = None


def _utc_now_naive() -> datetime:
    """Return a naive UTC datetime without deprecated utcnow()."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def invalidate_ai_model_catalog_cache() -> None:
    """Clear cached `/api/health/ai/models` data after runtime model changes."""
    global _last_ai_models_result, _last_ai_models_at
    _last_ai_models_result = None
    _last_ai_models_at = None


def _active_google_provider() -> str:
    transport = str(settings.google_gemini_transport).strip().lower()
    return "google-aistudio" if transport == "aistudio" else "google-vertex"


def _current_runtime_llm() -> dict[str, str | None]:
    provider = normalise_llm_provider(settings.llm_provider)
    if provider == "google":
        active_provider = _active_google_provider()
    else:
        active_provider = provider
    model_by_provider = {
        "anthropic": settings.llm_model_anthropic,
        "openai": settings.llm_model_openai,
        "google": settings.llm_model_google,
    }
    return {
        "provider": active_provider,
        "model": model_by_provider.get(provider, ""),
        "google_gemini_transport": settings.google_gemini_transport if provider == "google" else None,
    }


async def ai_model_catalog_health_check(force: bool = False) -> dict:
    """Return smoke-tested available LLM models only."""
    global _last_ai_models_result, _last_ai_models_at

    now = _utc_now_naive()
    if (
        not force
        and _last_ai_models_result is not None
        and _last_ai_models_at is not None
        and (now - _last_ai_models_at) <= AI_MODEL_HEALTH_CACHE_TTL
    ):
        return {
            **_last_ai_models_result,
            "cached": True,
            "checked_at": _last_ai_models_at.isoformat() + "Z",
        }

    smoke_results = await smoke_test_supported_models(
        anthropic_key=settings.anthropic_api_key,
        openai_key=settings.openai_api_key,
        google_api_key=settings.google_api_key,
        google_credentials_path=settings.google_application_credentials,
        google_credentials_host_path=settings.google_application_credentials_host_path,
        google_project_id=settings.google_cloud_project_id,
        google_location=settings.google_vertex_gemini_location,
    )
    payload = {
        "current": _current_runtime_llm(),
        "smoke_tested_models": smoke_results,
    }
    _last_ai_models_result = payload
    _last_ai_models_at = now
    return {
        **payload,
        "cached": False,
        "checked_at": now.isoformat() + "Z",
    }


@router.get("/ai")
async def ai_health_check(force: bool = False):
    """Check that external LLM service API keys are valid."""
    global _last_ai_health_result, _last_ai_health_at

    now = _utc_now_naive()
    if (
        not force
        and _last_ai_health_result is not None
        and _last_ai_health_at is not None
        and (now - _last_ai_health_at) <= AI_HEALTH_CACHE_TTL
    ):
        return {
            **_last_ai_health_result,
            "cached": True,
            "checked_at": _last_ai_health_at.isoformat() + "Z",
        }

    results = await verify_all_keys(
        anthropic_key=settings.anthropic_api_key,
        openai_key=settings.openai_api_key,
        google_api_key=settings.google_api_key,
        google_credentials_path=settings.google_application_credentials,
        google_credentials_host_path=settings.google_application_credentials_host_path,
        google_project_id=settings.google_cloud_project_id,
        google_model_id=settings.llm_model_google,
        google_location=settings.google_vertex_gemini_location,
        anthropic_model_id=settings.llm_model_anthropic,
        openai_model_id=settings.llm_model_openai,
    )
    _last_ai_health_result = results
    _last_ai_health_at = now
    return {
        **results,
        "cached": False,
        "checked_at": now.isoformat() + "Z",
    }


@router.get("/ai/models")
async def ai_models_health_api(force: bool = False):
    """Return smoke-tested available LLM models."""
    return await ai_model_catalog_health_check(force=force)
