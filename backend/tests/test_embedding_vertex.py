"""Vertex embedding provider tests."""

from __future__ import annotations

import pytest

from app.ai.embedding_vertex import VertexEmbeddingService


class _FakeTokenProvider:
    async def get_access_token(self) -> str:
        return "vertex-token"


class _FakePostResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = "error"

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    last_post: dict | None = None
    posts: list[dict] = []

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def aclose(self) -> None:
        return None

    async def post(self, url, json=None, headers=None):
        payload = {"url": url, "json": json, "headers": headers}
        _FakeAsyncClient.last_post = payload
        _FakeAsyncClient.posts.append(payload)
        instances = json["instances"]
        predictions = []
        for item in instances:
            if "text" in item:
                predictions.append({"textEmbedding": [0.1, 0.2, 0.3]})
            else:
                predictions.append({"imageEmbedding": [0.4, 0.5, 0.6]})
        return _FakePostResponse({"predictions": predictions})


@pytest.mark.asyncio
async def test_vertex_embedding_text_payload_and_parsing(monkeypatch) -> None:
    monkeypatch.setattr("app.ai.embedding_vertex.httpx.AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.posts = []
    service = VertexEmbeddingService(
        token_provider=_FakeTokenProvider(),
        project_id="p1",
        location="us-central1",
        model_id="multimodalembedding@001",
        dimension=256,
    )

    result = await service.embed_batch(["hello", "world"])

    assert result == [[0.1, 0.2, 0.3], [0.1, 0.2, 0.3]]
    post = _FakeAsyncClient.last_post or {}
    assert "models/multimodalembedding@001:predict" in post["url"]
    assert post["headers"]["Authorization"] == "Bearer vertex-token"
    assert post["json"]["parameters"]["dimension"] == 256
    assert len(_FakeAsyncClient.posts) == 2
    assert _FakeAsyncClient.posts[0]["json"]["instances"] == [{"text": "hello"}]
    assert _FakeAsyncClient.posts[1]["json"]["instances"] == [{"text": "world"}]
    await service.close()


@pytest.mark.asyncio
async def test_vertex_embedding_image_payload_and_parsing(monkeypatch) -> None:
    monkeypatch.setattr("app.ai.embedding_vertex.httpx.AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.posts = []
    service = VertexEmbeddingService(
        token_provider=_FakeTokenProvider(),
        project_id="p1",
        location="us-central1",
        model_id="multimodalembedding@001",
        dimension=256,
    )

    result = await service.embed_image(b"png-bytes", "image/png")

    assert result == [0.4, 0.5, 0.6]
    post = _FakeAsyncClient.last_post or {}
    assert "bytesBase64Encoded" in post["json"]["instances"][0]["image"]
    await service.close()
