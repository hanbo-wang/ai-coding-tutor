"""EmbeddingService provider ordering and fallback tests."""

from __future__ import annotations

import pytest

from app.ai.embedding_service import EmbeddingService


class _DummyProvider:
    def __init__(self, name: str, *args, **kwargs) -> None:
        self.name = name
        self.calls = 0
        self.raise_on_batch = False

    async def close(self) -> None:
        return None

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        if self.raise_on_batch:
            raise RuntimeError(f"{self.name} failed")
        return [[1.0, 0.0] for _ in texts]

class _DummyTokenProvider:
    def __init__(self, credentials_path: str) -> None:
        self.credentials_path = credentials_path


@pytest.mark.asyncio
async def test_embedding_service_prefers_vertex_then_fallbacks(monkeypatch) -> None:
    created: dict[str, _DummyProvider] = {}

    def _vertex_factory(*args, **kwargs):
        provider = _DummyProvider("vertex")
        created["vertex"] = provider
        return provider

    def _cohere_factory(*args, **kwargs):
        provider = _DummyProvider("cohere")
        created["cohere"] = provider
        return provider

    def _voyage_factory(*args, **kwargs):
        provider = _DummyProvider("voyage")
        created["voyage"] = provider
        return provider

    monkeypatch.setattr("app.ai.embedding_service.GoogleServiceAccountTokenProvider", _DummyTokenProvider)
    monkeypatch.setattr("app.ai.embedding_service.resolve_google_project_id", lambda *a, **k: "proj")
    monkeypatch.setattr("app.ai.embedding_service.VertexEmbeddingService", _vertex_factory)
    monkeypatch.setattr("app.ai.embedding_service.CohereEmbeddingService", _cohere_factory)
    monkeypatch.setattr("app.ai.embedding_service.VoyageEmbeddingService", _voyage_factory)

    service = EmbeddingService(
        provider="vertex",
        google_application_credentials="/tmp/service.json",
        vertex_location="europe-west2",
        cohere_model_id="embed-v4.0",
        vertex_model_id="multimodalembedding@001",
        voyage_model_id="voyage-multimodal-3.5",
        cohere_api_key="coh",
        voyage_api_key="voy",
    )

    created["vertex"].raise_on_batch = True
    result = await service.embed_text("hello")

    assert result == [1.0, 0.0]
    assert created["vertex"].calls == 1
    assert created["cohere"].calls == 1
    assert len(service._fallbacks) == 2  # noqa: SLF001 - intentional internal check
    await service.close()
