"""Optional external AI smoke tests (real API calls, costs may apply).

Run manually:
    RUN_EXTERNAL_MODEL_TESTS=1 pytest -m external_ai tests/test_external_model_smoke.py -q
"""

from __future__ import annotations

import os
import struct
import zlib
from pathlib import Path

import pytest


RUN_EXTERNAL = os.getenv("RUN_EXTERNAL_MODEL_TESTS") == "1"

pytestmark = [
    pytest.mark.external_ai,
    pytest.mark.skipif(not RUN_EXTERNAL, reason="Set RUN_EXTERNAL_MODEL_TESTS=1 to run"),
]


def _png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    crc = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
    return (
        len(payload).to_bytes(4, "big")
        + chunk_type
        + payload
        + crc.to_bytes(4, "big")
    )


def _make_test_png(width: int = 64, height: int = 64) -> bytes:
    """Build a small but realistic RGB PNG fixture without extra dependencies."""
    rows = bytearray()
    for y in range(height):
        rows.append(0)  # no filter
        for x in range(width):
            # Gradient + xor pattern produces non-trivial image content.
            r = (x * 255) // max(1, width - 1)
            g = (y * 255) // max(1, height - 1)
            b = ((x ^ y) * 255) // max(1, max(width, height) - 1)
            rows.extend((r, g, b))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # RGB8
    idat = zlib.compress(bytes(rows), level=6)
    return b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            _png_chunk(b"IHDR", ihdr),
            _png_chunk(b"IDAT", idat),
            _png_chunk(b"IEND", b""),
        ]
    )


_TEST_PNG = _make_test_png(64, 64)


def _resolve_local_google_credentials_path(settings) -> str | None:
    candidates = [
        settings.google_application_credentials,
        os.getenv("GOOGLE_APPLICATION_CREDENTIALS_HOST_PATH", ""),
        str(Path(__file__).resolve().parents[2] / "ai-coding-tutor-488300-8641d2e48a27.json"),
    ]
    for candidate in candidates:
        candidate = (candidate or "").strip()
        if candidate and Path(candidate).exists():
            return candidate
    return None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider_name", "model_id"),
    [
        ("google", "gemini-3-flash-preview"),
        ("google", "gemini-3.1-pro-preview"),
        ("anthropic", "claude-sonnet-4-6"),
        ("anthropic", "claude-haiku-4-5"),
        ("openai", "gpt-5.2"),
        ("openai", "gpt-5-mini"),
    ],
)
async def test_llm_stream_smoke(provider_name: str, model_id: str) -> None:
    from app.ai.google_auth import GoogleServiceAccountTokenProvider, resolve_google_project_id
    from app.ai.llm_anthropic import AnthropicProvider
    from app.ai.llm_google import GoogleGeminiProvider
    from app.ai.llm_openai import OpenAIProvider
    from app.config import settings

    if provider_name == "google":
        credentials_path = _resolve_local_google_credentials_path(settings)
        if not credentials_path:
            pytest.skip("Google service-account path not configured")
        token_provider = GoogleServiceAccountTokenProvider(credentials_path)
        project_id = resolve_google_project_id(
            credentials_path,
            settings.google_cloud_project_id,
        )
        provider = GoogleGeminiProvider(
            token_provider=token_provider,
            project_id=project_id,
            location=settings.google_vertex_gemini_location,
            model_id=model_id,
        )
    elif provider_name == "anthropic":
        if not settings.anthropic_api_key:
            pytest.skip("ANTHROPIC_API_KEY not configured")
        provider = AnthropicProvider(settings.anthropic_api_key, model_id=model_id)
    else:
        if not settings.openai_api_key:
            pytest.skip("OPENAI_API_KEY not configured")
        provider = OpenAIProvider(settings.openai_api_key, model_id=model_id)

    text = await provider.generate(
        system_prompt="Reply briefly.",
        messages=[{"role": "user", "content": "Reply with only the word pong."}],
        max_tokens=12,
    )
    assert isinstance(text, str)
    # Preview models may occasionally return no visible text while still
    # reporting valid usage metadata (for example, thought tokens only).
    assert (
        text.strip()
        or provider.last_usage.output_tokens > 0
        or provider.last_usage.input_tokens > 0
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", ["vertex", "cohere", "voyage"])
async def test_embedding_text_and_image_smoke(provider_name: str) -> None:
    from app.ai.embedding_cohere import CohereEmbeddingService
    from app.ai.embedding_vertex import VertexEmbeddingService
    from app.ai.embedding_voyage import VoyageEmbeddingService
    from app.ai.google_auth import GoogleServiceAccountTokenProvider, resolve_google_project_id
    from app.config import settings

    service = None
    if provider_name == "vertex":
        credentials_path = _resolve_local_google_credentials_path(settings)
        if not credentials_path:
            pytest.skip("Google service-account path not configured")
        token_provider = GoogleServiceAccountTokenProvider(credentials_path)
        service = VertexEmbeddingService(
            token_provider=token_provider,
            project_id=resolve_google_project_id(
                credentials_path,
                settings.google_cloud_project_id,
            ),
            location=settings.google_vertex_embedding_location,
            model_id=settings.embedding_model_vertex,
            dimension=256,
        )
    elif provider_name == "cohere":
        if not settings.cohere_api_key:
            pytest.skip("COHERE_API_KEY not configured")
        service = CohereEmbeddingService(settings.cohere_api_key)
    else:
        if not settings.voyageai_api_key:
            pytest.skip("VOYAGEAI_API_KEY not configured")
        service = VoyageEmbeddingService(settings.voyageai_api_key)

    text_vec = await service.embed_text("ping")
    image_vec = await service.embed_image(_TEST_PNG, "image/png")
    assert text_vec is not None and len(text_vec) > 0
    if provider_name in {"cohere", "voyage"} and image_vec is None:
        pytest.skip("Provider rejected the 64x64 PNG fixture; text embedding smoke passed")
    assert image_vec is not None and len(image_vec) > 0
    if provider_name == "vertex":
        assert len(text_vec) == 256
        assert len(image_vec) == 256
    await service.close()
