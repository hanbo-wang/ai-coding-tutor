"""Verify that external AI provider credentials are valid."""

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
    SUPPORTED_EMBEDDING_MODELS,
    SUPPORTED_LLM_MODELS,
    validate_supported_embedding_model,
    validate_supported_llm_model,
)

logger = logging.getLogger(__name__)

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
    except Exception as e:
        logger.error("Anthropic key verification failed: %s", e)
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
    except Exception as e:
        logger.error("OpenAI key verification failed: %s", e)
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
    if not credentials_path:
        return False
    try:
        model_id = validate_supported_llm_model("google", model_id)
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
    except Exception as e:
        logger.error("Google key verification failed: %s", e)
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
    except Exception as e:
        logger.error("Google AI Studio key verification failed: %s", e)
        return False


async def verify_vertex_embedding_key(
    credentials_path: str,
    model_id: str,
    project_id: str = "",
    location: str = "",
    host_credentials_path: str = "",
) -> bool:
    """Test Vertex multimodal embedding access using service-account credentials."""
    if not credentials_path:
        return False
    try:
        model_id = validate_supported_embedding_model("vertex", model_id)
        token, resolved_project_id = await _get_vertex_auth_context(
            credentials_path,
            project_id,
            host_credentials_path,
        )
        url = (
            f"https://{location}-aiplatform.googleapis.com/v1/projects/"
            f"{resolved_project_id}/locations/{location}/publishers/google/models/"
            f"{model_id}:predict"
        )
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={
                    "instances": [{"text": "ping"}],
                    "parameters": {"dimension": 256},
                },
            )
            if response.status_code == 200:
                logger.info("Vertex embedding credentials are valid")
                return True
            logger.warning("Vertex embedding returned %d: %s", response.status_code, response.text)
            return response.status_code not in (400, 401, 403)
    except Exception as e:
        logger.error("Vertex embedding verification failed: %s", e)
        return False


async def verify_cohere_key(api_key: str, model_id: str) -> bool:
    """Test Cohere API key with the same embed endpoint used in app code."""
    if not api_key:
        return False
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                "https://api.cohere.com/v2/embed",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": validate_supported_embedding_model("cohere", model_id),
                    "input_type": "search_query",
                    "texts": ["ping"],
                    "embedding_types": ["float"],
                    "output_dimension": 256,
                },
            )
            if response.status_code == 200:
                logger.info("Cohere API key is valid")
                return True
            logger.warning("Cohere API returned %d: %s", response.status_code, response.text)
            return response.status_code not in (401, 403)
    except Exception as e:
        logger.error("Cohere key verification failed: %s", e)
        return False


async def verify_voyage_key(api_key: str, model_id: str) -> bool:
    """Test Voyage AI API key by sending a minimal embedding request."""
    if not api_key:
        return False
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                "https://api.voyageai.com/v1/multimodalembeddings",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": validate_supported_embedding_model("voyage", model_id),
                    "inputs": [{"content": [{"type": "text", "text": "test"}]}],
                },
            )
            if response.status_code == 200:
                logger.info("Voyage AI API key is valid")
                return True
            logger.warning("Voyage AI returned %d: %s", response.status_code, response.text)
            return response.status_code not in (401, 403)
    except Exception as e:
        logger.error("Voyage AI key verification failed: %s", e)
        return False


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


async def _smoke_test_model_list(model_ids: set[str], verifier, *args, **kwargs) -> dict[str, bool]:
    ordered_models = sorted(model_ids)
    results = await asyncio.gather(
        *(verifier(*args, model_id=model_id, **kwargs) for model_id in ordered_models)
    )
    return dict(zip(ordered_models, results, strict=False))


def _empty_smoke_group(reason: str, *, extra: dict | None = None) -> dict:
    payload = {
        "configured": False,
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
    payload = {
        "configured": True,
        "checked_models": checked_models,
        "available_models": [model_id for model_id, ok in checked_models.items() if ok],
    }
    if extra:
        payload.update(extra)
    return payload


async def smoke_test_supported_models(
    *,
    anthropic_key: str = "",
    openai_key: str = "",
    google_transport: str = "",
    google_api_key: str = "",
    google_credentials_path: str = "",
    google_credentials_host_path: str = "",
    google_project_id: str = "",
    google_location: str = "",
    cohere_key: str = "",
    voyage_key: str = "",
    vertex_embedding_location: str = "",
) -> dict[str, dict]:
    """Run model-level smoke checks for configured providers and return available models."""
    llm_results: dict[str, dict] = {}
    embedding_results: dict[str, dict] = {}

    if anthropic_key:
        checked = await _smoke_test_model_list(
            SUPPORTED_LLM_MODELS["anthropic"],
            verify_anthropic_key,
            anthropic_key,
        )
        llm_results["anthropic"] = _smoke_group_from_results(checked)
    else:
        llm_results["anthropic"] = _empty_smoke_group("ANTHROPIC_API_KEY is not configured")

    if openai_key:
        checked = await _smoke_test_model_list(
            SUPPORTED_LLM_MODELS["openai"],
            verify_openai_key,
            openai_key,
        )
        llm_results["openai"] = _smoke_group_from_results(checked)
    else:
        llm_results["openai"] = _empty_smoke_group("OPENAI_API_KEY is not configured")

    transport = _normalise_google_transport(google_transport)
    google_extra = {"transport": transport or "unset"}
    if transport == "aistudio":
        if google_api_key:
            checked = await _smoke_test_model_list(
                SUPPORTED_LLM_MODELS["google"],
                verify_google_ai_studio_key,
                google_api_key,
            )
            llm_results["google"] = _smoke_group_from_results(checked, extra=google_extra)
        else:
            llm_results["google"] = _empty_smoke_group(
                "GOOGLE_GEMINI_TRANSPORT=aistudio but GOOGLE_API_KEY is not configured",
                extra=google_extra,
            )
    elif transport == "vertex":
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
            llm_results["google"] = _smoke_group_from_results(checked, extra=google_extra)
        else:
            llm_results["google"] = _empty_smoke_group(
                "GOOGLE_GEMINI_TRANSPORT=vertex but Google service-account credentials are not configured",
                extra=google_extra,
            )
    else:
        llm_results["google"] = _empty_smoke_group(
            "Set GOOGLE_GEMINI_TRANSPORT to 'aistudio' or 'vertex'",
            extra=google_extra,
        )

    if cohere_key:
        checked = await _smoke_test_model_list(
            SUPPORTED_EMBEDDING_MODELS["cohere"],
            verify_cohere_key,
            cohere_key,
        )
        embedding_results["cohere"] = _smoke_group_from_results(checked)
    else:
        embedding_results["cohere"] = _empty_smoke_group("COHERE_API_KEY is not configured")

    vertex_credential_candidate = (
        google_credentials_path
        or google_credentials_host_path
        or ""
    ).strip()
    if vertex_credential_candidate:
        checked = await _smoke_test_model_list(
            SUPPORTED_EMBEDDING_MODELS["vertex"],
            verify_vertex_embedding_key,
            google_credentials_path,
            project_id=google_project_id,
            location=vertex_embedding_location,
            host_credentials_path=google_credentials_host_path,
        )
        embedding_results["vertex"] = _smoke_group_from_results(checked)
    else:
        embedding_results["vertex"] = _empty_smoke_group(
            "Google service-account credentials are not configured for Vertex embeddings"
        )

    if voyage_key:
        checked = await _smoke_test_model_list(
            SUPPORTED_EMBEDDING_MODELS["voyage"],
            verify_voyage_key,
            voyage_key,
        )
        embedding_results["voyage"] = _smoke_group_from_results(checked)
    else:
        embedding_results["voyage"] = _empty_smoke_group("VOYAGEAI_API_KEY is not configured")

    return {
        "llm": llm_results,
        "embeddings": embedding_results,
    }


async def verify_all_keys(
    anthropic_key: str = "",
    openai_key: str = "",
    google_transport: str = "",
    google_api_key: str = "",
    google_credentials_path: str = "",
    google_credentials_host_path: str = "",
    google_project_id: str = "",
    google_model_id: str = "",
    anthropic_model_id: str = "",
    openai_model_id: str = "",
    vertex_embedding_model_id: str = "",
    cohere_model_id: str = "",
    voyage_model_id: str = "",
    google_location: str = "",
    vertex_embedding_location: str = "",
    cohere_key: str = "",
    voyage_key: str = "",
) -> dict[str, bool]:
    """Verify all configured API keys concurrently."""
    transport = str(google_transport or "").strip().lower().replace("-", "_")
    if transport in {"aistudio", "ai_studio", "studio"}:
        google_task = verify_google_ai_studio_key(google_api_key, google_model_id)
    elif transport in {"vertex", "vertex_ai"}:
        google_task = verify_google_key(
            google_credentials_path,
            project_id=google_project_id,
            model_id=google_model_id,
            location=google_location,
            host_credentials_path=google_credentials_host_path,
        )
    else:
        logger.warning(
            "Google LLM verification skipped: set GOOGLE_GEMINI_TRANSPORT to 'aistudio' or 'vertex'"
        )

        async def _google_transport_not_configured() -> bool:
            return False

        google_task = _google_transport_not_configured()
    results = await asyncio.gather(
        verify_anthropic_key(anthropic_key, anthropic_model_id),
        verify_openai_key(openai_key, openai_model_id),
        google_task,
        verify_vertex_embedding_key(
            google_credentials_path,
            project_id=google_project_id,
            model_id=vertex_embedding_model_id,
            location=vertex_embedding_location,
            host_credentials_path=google_credentials_host_path,
        ),
        verify_cohere_key(cohere_key, cohere_model_id),
        verify_voyage_key(voyage_key, voyage_model_id),
    )
    return {
        "anthropic": results[0],
        "openai": results[1],
        "google": results[2],
        "vertex_embedding": results[3],
        "cohere": results[4],
        "voyageai": results[5],
    }


if __name__ == "__main__":
    sys.path.insert(0, ".")
    from app.config import settings

    async def main():
        results = await verify_all_keys(
            anthropic_key=settings.anthropic_api_key,
            openai_key=settings.openai_api_key,
            google_transport=settings.google_gemini_transport,
            google_api_key=settings.google_api_key,
            google_credentials_path=settings.google_application_credentials,
            google_credentials_host_path=settings.google_application_credentials_host_path,
            google_project_id=settings.google_cloud_project_id,
            google_model_id=settings.llm_model_google,
            google_location=settings.google_vertex_gemini_location,
            anthropic_model_id=settings.llm_model_anthropic,
            openai_model_id=settings.llm_model_openai,
            vertex_embedding_model_id=settings.embedding_model_vertex,
            vertex_embedding_location=settings.google_vertex_embedding_location,
            cohere_model_id=settings.embedding_model_cohere,
            cohere_key=settings.cohere_api_key,
            voyage_model_id=settings.embedding_model_voyage,
            voyage_key=settings.voyageai_api_key,
        )
        llm_ok = results["anthropic"] or results["openai"] or results["google"]

        # Print simple grouped results for quick troubleshooting.
        print("LLM APIs:")
        for service in ("anthropic", "openai", "google"):
            status = "OK" if results[service] else "FAILED"
            print(f"  {service}: {status}")

        print("Embedding APIs:")
        for service in ("vertex_embedding", "cohere", "voyageai"):
            status = "OK" if results[service] else "FAILED"
            print(f"  {service}: {status}")

        # Allow startup when at least one LLM provider works.
        if llm_ok:
            sys.exit(0)
        sys.exit(2)

    asyncio.run(main())
