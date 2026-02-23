"""Health check endpoints."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter

from app.ai.verify_keys import verify_all_keys
from app.config import settings

router = APIRouter(prefix="/api/health", tags=["health"])
AI_HEALTH_CACHE_TTL = timedelta(seconds=30)
_last_ai_health_result: dict[str, bool] | None = None
_last_ai_health_at: datetime | None = None


def _utc_now_naive() -> datetime:
    """Return a naive UTC datetime without deprecated utcnow()."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


@router.get("/ai")
async def ai_health_check(force: bool = False):
    """Check that external AI service API keys are valid."""
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
        settings.anthropic_api_key,
        settings.openai_api_key,
        settings.google_application_credentials,
        settings.google_cloud_project_id,
        settings.llm_model_google,
        settings.google_vertex_gemini_location,
        settings.embedding_model_vertex,
        settings.google_vertex_embedding_location,
        settings.cohere_api_key,
        settings.voyageai_api_key,
    )
    _last_ai_health_result = results
    _last_ai_health_at = now
    return {
        **results,
        "cached": False,
        "checked_at": now.isoformat() + "Z",
    }
