"""Verify that external LLM provider credentials are valid."""

import asyncio
import logging
import sys

import httpx

from app.ai.google_auth import (
    GoogleServiceAccountTokenProvider,
    resolve_google_credentials_path,
    resolve_google_project_id,
)
from app.ai.model_registry import (
    SUPPORTED_LLM_MODELS,
    normalise_google_vertex_location,
    validate_supported_llm_model,
)

logger = logging.getLogger(__name__)

GOOGLE_AI_STUDIO_PROVIDER = "google-aistudio"
GOOGLE_VERTEX_PROVIDER = "google-vertex"


async def verify_anthropic_key(api_key: str, model_id: str) -> bool:
    """Test Anthropic API key by sending a minimal request."""
    if not api_key:
        return False
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": validate_supported_llm_model("anthropic", model_id),
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "ping"}],
                },
            )
            if response.status_code == 200:
                logger.info("Anthropic API key is valid")
                return True
            logger.warning("Anthropic API returned %d: %s", response.status_code, response.text)
            return response.status_code not in (401, 403)
    except Exception as exc:  # pragma: no cover - network failure branch
        logger.error("Anthropic key verification failed: %s", exc)
        return False


async def verify_openai_key(api_key: str, model_id: str) -> bool:
    """Test OpenAI API key by sending a minimal request."""
    if not api_key:
        return False
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": validate_supported_llm_model("openai", model_id),
                    "max_completion_tokens": 1,
                    "messages": [{"role": "user", "content": "ping"}],
                },
            )
            if response.status_code == 200:
                logger.info("OpenAI API key is valid")
                return True
            logger.warning("OpenAI API returned %d: %s", response.status_code, response.text)
            return response.status_code not in (401, 403)
    except Exception as exc:  # pragma: no cover - network failure branch
        logger.error("OpenAI key verification failed: %s", exc)
        return False


async def _get_vertex_auth_context(
    credentials_path: str,
    explicit_project_id: str = "",
    host_credentials_path: str = "",
) -> tuple[str, str]:
    resolved_path = resolve_google_credentials_path(
        credentials_path,
        host_credentials_path,
    )
    token_provider = GoogleServiceAccountTokenProvider(resolved_path)
    token = await token_provider.get_access_token()
    project_id = resolve_google_project_id(resolved_path, explicit_project_id)
    return token, project_id


async def verify_google_key(
    credentials_path: str,
    model_id: str,
    project_id: str = "",
    location: str = "",
    host_credentials_path: str = "",
) -> bool:
    """Test Vertex Gemini access using service-account credentials."""
    credential_candidate = (
        credentials_path
        or host_credentials_path
        or ""
    ).strip()
    if not credential_candidate:
        return False
    try:
        model_id = validate_supported_llm_model("google", model_id)
        location = normalise_google_vertex_location(location, model_id)
        token, resolved_project_id = await _get_vertex_auth_context(
            credentials_path,
            project_id,
            host_credentials_path,
        )
        host = (
            "aiplatform.googleapis.com"
            if location == "global"
            else f"{location}-aiplatform.googleapis.com"
        )
        url = (
            f"https://{host}/v1/projects/"
            f"{resolved_project_id}/locations/{location}/publishers/google/models/"
            f"{model_id}:generateContent"
        )
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={
                    "contents": [{"role": "user", "parts": [{"text": "ping"}]}],
                    "generationConfig": {"maxOutputTokens": 1},
                },
            )
            if response.status_code == 200:
                logger.info("Google Vertex Gemini credentials are valid")
                return True
            logger.warning("Google Vertex Gemini returned %d: %s", response.status_code, response.text)
            return response.status_code not in (400, 401, 403)
    except Exception as exc:  # pragma: no cover - network failure branch
        logger.error("Google Vertex key verification failed: %s", exc)
        return False


async def verify_google_ai_studio_key(api_key: str, model_id: str) -> bool:
    """Test Google AI Studio / Gemini API access using an API key."""
    if not api_key:
        return False
    try:
        model_id = validate_supported_llm_model("google", model_id)
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model_id}:generateContent"
        )
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                url,
                headers={
                    "x-goog-api-key": api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "contents": [{"role": "user", "parts": [{"text": "ping"}]}],
                    "generationConfig": {"maxOutputTokens": 1},
                },
            )
            if response.status_code == 200:
                logger.info("Google AI Studio Gemini API key is valid")
                return True
            logger.warning("Google AI Studio Gemini returned %d: %s", response.status_code, response.text)
            return response.status_code not in (400, 401, 403)
    except Exception as exc:  # pragma: no cover - network failure branch
        logger.error("Google AI Studio key verification failed: %s", exc)
        return False


async def _smoke_test_model_list(model_ids: set[str], verifier, *args, **kwargs) -> dict[str, bool]:
    ordered_models = sorted(model_ids)
    results = await asyncio.gather(
        *(verifier(*args, model_id=model_id, **kwargs) for model_id in ordered_models)
    )
    return dict(zip(ordered_models, results, strict=False))


def _empty_smoke_group(reason: str, *, extra: dict | None = None) -> dict:
    payload = {
        "ready": False,
        "reason": reason,
        "checked_models": {},
        "available_models": [],
    }
    if extra:
        payload.update(extra)
    return payload


def _smoke_group_from_results(
    checked_models: dict[str, bool],
    *,
    extra: dict | None = None,
) -> dict:
    available_models = [model_id for model_id, ok in checked_models.items() if ok]
    payload = {
        "ready": bool(available_models),
        "reason": "" if available_models else "No models passed smoke checks",
        "checked_models": checked_models,
        "available_models": available_models,
    }
    if extra:
        payload.update(extra)
    return payload


async def smoke_test_supported_models(
    *,
    anthropic_key: str = "",
    openai_key: str = "",
    google_api_key: str = "",
    google_credentials_path: str = "",
    google_credentials_host_path: str = "",
    google_project_id: str = "",
    google_location: str = "",
) -> dict[str, dict]:
    """Run model-level smoke checks for configured LLM providers."""
    llm_results: dict[str, dict] = {}

    if anthropic_key:
        checked = await _smoke_test_model_list(
            SUPPORTED_LLM_MODELS["anthropic"],
            verify_anthropic_key,
            anthropic_key,
        )
        llm_results["anthropic"] = _smoke_group_from_results(checked)
    else:
        llm_results["anthropic"] = _empty_smoke_group("ANTHROPIC_API_KEY is not set")

    if openai_key:
        checked = await _smoke_test_model_list(
            SUPPORTED_LLM_MODELS["openai"],
            verify_openai_key,
            openai_key,
        )
        llm_results["openai"] = _smoke_group_from_results(checked)
    else:
        llm_results["openai"] = _empty_smoke_group("OPENAI_API_KEY is not set")

    if google_api_key:
        checked = await _smoke_test_model_list(
            SUPPORTED_LLM_MODELS["google"],
            verify_google_ai_studio_key,
            google_api_key,
        )
        llm_results[GOOGLE_AI_STUDIO_PROVIDER] = _smoke_group_from_results(
            checked,
            extra={"transport": "aistudio"},
        )
    else:
        llm_results[GOOGLE_AI_STUDIO_PROVIDER] = _empty_smoke_group(
            "GOOGLE_API_KEY is not set",
            extra={"transport": "aistudio"},
        )

    google_credential_candidate = (
        google_credentials_path
        or google_credentials_host_path
        or ""
    ).strip()
    if google_credential_candidate:
        checked = await _smoke_test_model_list(
            SUPPORTED_LLM_MODELS["google"],
            verify_google_key,
            google_credentials_path,
            project_id=google_project_id,
            location=google_location,
            host_credentials_path=google_credentials_host_path,
        )
        llm_results[GOOGLE_VERTEX_PROVIDER] = _smoke_group_from_results(
            checked,
            extra={"transport": "vertex"},
        )
    else:
        llm_results[GOOGLE_VERTEX_PROVIDER] = _empty_smoke_group(
            "Google service-account credentials are not set",
            extra={"transport": "vertex"},
        )

    return {"llm": llm_results}


async def verify_all_keys(
    anthropic_key: str = "",
    openai_key: str = "",
    google_api_key: str = "",
    google_credentials_path: str = "",
    google_credentials_host_path: str = "",
    google_project_id: str = "",
    google_model_id: str = "",
    anthropic_model_id: str = "",
    openai_model_id: str = "",
    google_location: str = "",
) -> dict[str, bool]:
    """Verify all configured LLM API keys concurrently."""

    async def _false() -> bool:
        return False

    google_ai_studio_task = (
        verify_google_ai_studio_key(google_api_key, google_model_id)
        if google_api_key
        else _false()
    )
    google_credential_candidate = (
        google_credentials_path
        or google_credentials_host_path
        or ""
    ).strip()
    google_vertex_task = (
        verify_google_key(
            google_credentials_path,
            project_id=google_project_id,
            model_id=google_model_id,
            location=google_location,
            host_credentials_path=google_credentials_host_path,
        )
        if google_credential_candidate
        else _false()
    )

    results = await asyncio.gather(
        verify_anthropic_key(anthropic_key, anthropic_model_id),
        verify_openai_key(openai_key, openai_model_id),
        google_ai_studio_task,
        google_vertex_task,
    )
    google_ai_studio_ok = bool(results[2])
    google_vertex_ok = bool(results[3])
    return {
        "anthropic": bool(results[0]),
        "openai": bool(results[1]),
        "google_ai_studio": google_ai_studio_ok,
        "google_vertex": google_vertex_ok,
        "google": google_ai_studio_ok or google_vertex_ok,
    }


if __name__ == "__main__":
    sys.path.insert(0, ".")
    from app.config import settings

    async def main() -> None:
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
        llm_ok = results["anthropic"] or results["openai"] or results["google"]

        print("LLM APIs:")
        for service in (
            "anthropic",
            "openai",
            "google_ai_studio",
            "google_vertex",
            "google",
        ):
            status = "OK" if results[service] else "FAILED"
            print(f"  {service}: {status}")

        sys.exit(0 if llm_ok else 2)

    asyncio.run(main())
