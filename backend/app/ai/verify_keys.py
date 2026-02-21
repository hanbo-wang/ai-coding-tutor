"""Verify that API keys for external services are valid."""

import asyncio
import logging
import sys

import httpx

logger = logging.getLogger(__name__)

ANTHROPIC_MODEL = "claude-sonnet-4-5-20250929"
OPENAI_MODEL = "gpt-5.2"
GOOGLE_MODEL = "gemini-3-pro-preview"
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
                    "max_tokens": 1,
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


async def verify_google_key(api_key: str) -> bool:
    """Test Google API key by sending a minimal Gemini request."""
    if not api_key:
        return False
    try:
        url = (
            "https://generativelanguage.googleapis.com/v1beta"
            f"/models/{GOOGLE_MODEL}:generateContent?key={api_key}"
        )
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                url,
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [{"parts": [{"text": "ping"}]}],
                    "generationConfig": {"maxOutputTokens": 1},
                },
            )
            if response.status_code == 200:
                logger.info("Google Gemini API key is valid")
                return True
            logger.warning("Google Gemini API returned %d: %s", response.status_code, response.text)
            return response.status_code not in (400, 401, 403)
    except Exception as e:
        logger.error("Google key verification failed: %s", e)
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
    google_key: str = "",
    cohere_key: str = "",
    voyage_key: str = "",
) -> dict[str, bool]:
    """Verify all configured API keys concurrently."""
    results = await asyncio.gather(
        verify_anthropic_key(anthropic_key),
        verify_openai_key(openai_key),
        verify_google_key(google_key),
        verify_cohere_key(cohere_key),
        verify_voyage_key(voyage_key),
    )
    return {
        "anthropic": results[0],
        "openai": results[1],
        "google": results[2],
        "cohere": results[3],
        "voyageai": results[4],
    }


if __name__ == "__main__":
    sys.path.insert(0, ".")
    from app.config import settings

    async def main():
        results = await verify_all_keys(
            settings.anthropic_api_key,
            settings.openai_api_key,
            settings.google_api_key,
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
        for service in ("cohere", "voyageai"):
            status = "OK" if results[service] else "FAILED"
            print(f"  {service}: {status}")

        # Allow startup when at least one LLM provider works.
        if llm_ok:
            sys.exit(0)
        sys.exit(2)

    asyncio.run(main())
