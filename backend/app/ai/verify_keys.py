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
    validate_supported_embedding_model,
    validate_supported_llm_model,
)

logger = logging.getLogger(__name__)

ANTHROPIC_MODEL = "claude-sonnet-4-6"
OPENAI_MODEL = "gpt-5.2"
GOOGLE_MODEL = "gemini-3-flash-preview"
VERTEX_EMBEDDING_MODEL = "multimodalembedding@001"
COHERE_MODEL = "embed-v4.0"
VOYAGE_MODEL = "voyage-multimodal-3.5"


async def verify_anthropic_key(api_key: str) -> bool:
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
                    "model": ANTHROPIC_MODEL,
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


async def verify_openai_key(api_key: str) -> bool:
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
                    "model": OPENAI_MODEL,
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
) -> tuple[str, str]:
    resolved_path = resolve_google_credentials_path(credentials_path)
    token_provider = GoogleServiceAccountTokenProvider(resolved_path)
    token = await token_provider.get_access_token()
    project_id = resolve_google_project_id(resolved_path, explicit_project_id)
    return token, project_id


async def verify_google_key(
    credentials_path: str,
    project_id: str = "",
    model_id: str = GOOGLE_MODEL,
    location: str = "global",
) -> bool:
    """Test Vertex Gemini access using service-account credentials."""
    if not credentials_path:
        return False
    try:
        model_id = validate_supported_llm_model("google", model_id)
        token, resolved_project_id = await _get_vertex_auth_context(
            credentials_path, project_id
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
                    "contents": [{"parts": [{"text": "ping"}]}],
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


async def verify_vertex_embedding_key(
    credentials_path: str,
    project_id: str = "",
    model_id: str = VERTEX_EMBEDDING_MODEL,
    location: str = "us-central1",
) -> bool:
    """Test Vertex multimodal embedding access using service-account credentials."""
    if not credentials_path:
        return False
    try:
        model_id = validate_supported_embedding_model("vertex", model_id)
        token, resolved_project_id = await _get_vertex_auth_context(
            credentials_path, project_id
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


async def verify_cohere_key(api_key: str) -> bool:
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
                    "model": COHERE_MODEL,
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


async def verify_voyage_key(api_key: str) -> bool:
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
                    "model": VOYAGE_MODEL,
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


async def verify_all_keys(
    anthropic_key: str = "",
    openai_key: str = "",
    google_credentials_path: str = "",
    google_project_id: str = "",
    google_model_id: str = GOOGLE_MODEL,
    google_location: str = "global",
    vertex_embedding_model_id: str = VERTEX_EMBEDDING_MODEL,
    vertex_embedding_location: str = "us-central1",
    cohere_key: str = "",
    voyage_key: str = "",
) -> dict[str, bool]:
    """Verify all configured API keys concurrently."""
    results = await asyncio.gather(
        verify_anthropic_key(anthropic_key),
        verify_openai_key(openai_key),
        verify_google_key(
            google_credentials_path,
            project_id=google_project_id,
            model_id=google_model_id,
            location=google_location,
        ),
        verify_vertex_embedding_key(
            google_credentials_path,
            project_id=google_project_id,
            model_id=vertex_embedding_model_id,
            location=vertex_embedding_location,
        ),
        verify_cohere_key(cohere_key),
        verify_voyage_key(voyage_key),
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
