"""AI provider verification tests."""

import pytest

from app.ai.verify_keys import (
    smoke_test_supported_models,
    verify_all_keys,
    verify_google_ai_studio_key,
    verify_google_key,
)


@pytest.mark.asyncio
async def test_verify_all_keys_includes_vertex_embedding(monkeypatch) -> None:
    async def _true(*args, **kwargs):
        return True

    async def _false(*args, **kwargs):
        return False

    monkeypatch.setattr("app.ai.verify_keys.verify_anthropic_key", _true)
    monkeypatch.setattr("app.ai.verify_keys.verify_openai_key", _false)
    monkeypatch.setattr("app.ai.verify_keys.verify_google_key", _true)
    monkeypatch.setattr("app.ai.verify_keys.verify_vertex_embedding_key", _true)
    monkeypatch.setattr("app.ai.verify_keys.verify_cohere_key", _false)
    monkeypatch.setattr("app.ai.verify_keys.verify_voyage_key", _true)

    result = await verify_all_keys(
        anthropic_key="a",
        openai_key="o",
        google_transport="vertex",
        google_credentials_path="/tmp/sa.json",
        google_project_id="proj",
        google_model_id="gemini-3-flash-preview",
        anthropic_model_id="claude-haiku-4-5",
        openai_model_id="gpt-5-mini",
        vertex_embedding_model_id="multimodalembedding@001",
        google_location="europe-west2",
        vertex_embedding_location="europe-west2",
        cohere_model_id="embed-v4.0",
        cohere_key="c",
        voyage_model_id="voyage-multimodal-3.5",
        voyage_key="v",
    )

    assert result == {
        "anthropic": True,
        "openai": False,
        "google": True,
        "vertex_embedding": True,
        "cohere": False,
        "voyageai": True,
    }


@pytest.mark.asyncio
async def test_verify_all_keys_uses_google_ai_studio_when_transport_selected(monkeypatch) -> None:
    calls = {"aistudio": 0, "vertex": 0}

    async def _true(*args, **kwargs):
        return True

    async def _google_aistudio(*args, **kwargs):
        calls["aistudio"] += 1
        return True

    async def _google_vertex(*args, **kwargs):
        calls["vertex"] += 1
        return True

    monkeypatch.setattr("app.ai.verify_keys.verify_anthropic_key", _true)
    monkeypatch.setattr("app.ai.verify_keys.verify_openai_key", _true)
    monkeypatch.setattr("app.ai.verify_keys.verify_google_ai_studio_key", _google_aistudio)
    monkeypatch.setattr("app.ai.verify_keys.verify_google_key", _google_vertex)
    monkeypatch.setattr("app.ai.verify_keys.verify_vertex_embedding_key", _true)
    monkeypatch.setattr("app.ai.verify_keys.verify_cohere_key", _true)
    monkeypatch.setattr("app.ai.verify_keys.verify_voyage_key", _true)

    result = await verify_all_keys(
        google_transport="aistudio",
        google_api_key="AIza-test",
        google_credentials_path="/tmp/sa.json",
        google_model_id="gemini-3-flash-preview",
        vertex_embedding_model_id="multimodalembedding@001",
        google_location="europe-west2",
        vertex_embedding_location="europe-west2",
        cohere_model_id="embed-v4.0",
        voyage_model_id="voyage-multimodal-3.5",
    )

    assert result["google"] is True
    assert calls == {"aistudio": 1, "vertex": 0}


class _FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "ok") -> None:
        self.status_code = status_code
        self.text = text


class _RecordingAsyncClient:
    last_url: str | None = None
    last_json: dict | None = None

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, headers=None, json=None):
        _RecordingAsyncClient.last_url = url
        _RecordingAsyncClient.last_json = json
        return _FakeResponse(200)


@pytest.mark.asyncio
async def test_verify_google_key_uses_global_vertex_host(monkeypatch) -> None:
    async def _fake_auth_context(
        credentials_path: str,
        explicit_project_id: str = "",
        host_credentials_path: str = "",
    ):
        return "token", "proj"

    monkeypatch.setattr("app.ai.verify_keys._get_vertex_auth_context", _fake_auth_context)
    monkeypatch.setattr("app.ai.verify_keys.httpx.AsyncClient", _RecordingAsyncClient)

    ok = await verify_google_key(
        "/tmp/fake.json",
        project_id="proj",
        model_id="gemini-3-flash-preview",
        location="global",
    )

    assert ok is True
    assert (
        _RecordingAsyncClient.last_url
        == "https://aiplatform.googleapis.com/v1/projects/proj/locations/global/"
        "publishers/google/models/gemini-3-flash-preview:generateContent"
    )
    assert _RecordingAsyncClient.last_json == {
        "contents": [{"role": "user", "parts": [{"text": "ping"}]}],
        "generationConfig": {"maxOutputTokens": 1},
    }


@pytest.mark.asyncio
async def test_verify_google_ai_studio_key_uses_gemini_api_host(monkeypatch) -> None:
    monkeypatch.setattr("app.ai.verify_keys.httpx.AsyncClient", _RecordingAsyncClient)

    ok = await verify_google_ai_studio_key(
        "AIza-test",
        model_id="gemini-3-flash-preview",
    )

    assert ok is True
    assert (
        _RecordingAsyncClient.last_url
        == "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-3-flash-preview:generateContent"
    )
    assert _RecordingAsyncClient.last_json == {
        "contents": [{"role": "user", "parts": [{"text": "ping"}]}],
        "generationConfig": {"maxOutputTokens": 1},
    }


@pytest.mark.asyncio
async def test_smoke_test_supported_models_returns_available_lists(monkeypatch) -> None:
    async def _anthropic(api_key: str, model_id: str) -> bool:
        return model_id == "claude-haiku-4-5"

    async def _openai(api_key: str, model_id: str) -> bool:
        return model_id == "gpt-5-mini"

    async def _google_vertex(credentials_path: str, model_id: str, **kwargs) -> bool:
        return model_id == "gemini-3-flash-preview"

    async def _vertex_embedding(credentials_path: str, model_id: str, **kwargs) -> bool:
        return model_id == "multimodalembedding@001"

    async def _cohere(api_key: str, model_id: str) -> bool:
        return True

    async def _voyage(api_key: str, model_id: str) -> bool:
        return False

    monkeypatch.setattr("app.ai.verify_keys.verify_anthropic_key", _anthropic)
    monkeypatch.setattr("app.ai.verify_keys.verify_openai_key", _openai)
    monkeypatch.setattr("app.ai.verify_keys.verify_google_key", _google_vertex)
    monkeypatch.setattr("app.ai.verify_keys.verify_vertex_embedding_key", _vertex_embedding)
    monkeypatch.setattr("app.ai.verify_keys.verify_cohere_key", _cohere)
    monkeypatch.setattr("app.ai.verify_keys.verify_voyage_key", _voyage)

    result = await smoke_test_supported_models(
        anthropic_key="ant",
        openai_key="open",
        google_transport="vertex",
        google_credentials_path="/tmp/sa.json",
        google_project_id="proj",
        google_location="europe-west2",
        cohere_key="coh",
        voyage_key="voy",
        vertex_embedding_location="europe-west2",
    )

    assert result["llm"]["google"]["transport"] == "vertex"
    assert result["llm"]["anthropic"]["available_models"] == ["claude-haiku-4-5"]
    assert result["llm"]["openai"]["available_models"] == ["gpt-5-mini"]
    assert result["llm"]["google"]["available_models"] == ["gemini-3-flash-preview"]
    assert result["embeddings"]["cohere"]["available_models"] == ["embed-v4.0"]
    assert result["embeddings"]["vertex"]["available_models"] == ["multimodalembedding@001"]
    assert result["embeddings"]["voyage"]["available_models"] == []
    assert result["embeddings"]["voyage"]["configured"] is True


@pytest.mark.asyncio
async def test_smoke_test_supported_models_uses_google_transport_for_aistudio(monkeypatch) -> None:
    calls = {"aistudio": 0, "vertex": 0}

    async def _false(*args, **kwargs) -> bool:
        return False

    async def _google_aistudio(api_key: str, model_id: str) -> bool:
        calls["aistudio"] += 1
        return model_id == "gemini-3.1-pro-preview"

    async def _google_vertex(*args, **kwargs) -> bool:
        calls["vertex"] += 1
        return True

    monkeypatch.setattr("app.ai.verify_keys.verify_anthropic_key", _false)
    monkeypatch.setattr("app.ai.verify_keys.verify_openai_key", _false)
    monkeypatch.setattr("app.ai.verify_keys.verify_google_ai_studio_key", _google_aistudio)
    monkeypatch.setattr("app.ai.verify_keys.verify_google_key", _google_vertex)
    monkeypatch.setattr("app.ai.verify_keys.verify_vertex_embedding_key", _false)
    monkeypatch.setattr("app.ai.verify_keys.verify_cohere_key", _false)
    monkeypatch.setattr("app.ai.verify_keys.verify_voyage_key", _false)

    result = await smoke_test_supported_models(
        google_transport="aistudio",
        google_api_key="AIza-test",
    )

    assert result["llm"]["google"]["transport"] == "aistudio"
    assert result["llm"]["google"]["available_models"] == ["gemini-3.1-pro-preview"]
    assert calls["aistudio"] == 2
    assert calls["vertex"] == 0
