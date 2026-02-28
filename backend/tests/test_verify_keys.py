"""LLM provider verification tests."""

import pytest

from app.ai.verify_keys import (
    GOOGLE_AI_STUDIO_PROVIDER,
    GOOGLE_VERTEX_PROVIDER,
    smoke_test_supported_models,
    verify_all_keys,
    verify_google_ai_studio_key,
    verify_google_key,
)


@pytest.mark.asyncio
async def test_verify_all_keys_includes_google_transport_breakdown(monkeypatch) -> None:
    async def _true(*args, **kwargs):
        return True

    async def _false(*args, **kwargs):
        return False

    monkeypatch.setattr("app.ai.verify_keys.verify_anthropic_key", _true)
    monkeypatch.setattr("app.ai.verify_keys.verify_openai_key", _false)
    monkeypatch.setattr("app.ai.verify_keys.verify_google_ai_studio_key", _true)
    monkeypatch.setattr("app.ai.verify_keys.verify_google_key", _false)

    result = await verify_all_keys(
        anthropic_key="a",
        openai_key="o",
        google_api_key="AIza-test",
        google_credentials_path="/tmp/sa.json",
        google_project_id="proj",
        google_model_id="gemini-3-flash-preview",
        anthropic_model_id="claude-haiku-4-5",
        openai_model_id="gpt-5-mini",
        google_location="europe-west2",
    )

    assert result == {
        "anthropic": True,
        "openai": False,
        "google_ai_studio": True,
        "google_vertex": False,
        "google": True,
    }


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
async def test_verify_google_key_uses_host_path_when_primary_path_empty(monkeypatch) -> None:
    calls = {"credentials_path": None, "host_path": None}

    async def _fake_auth_context(
        credentials_path: str,
        explicit_project_id: str = "",
        host_credentials_path: str = "",
    ):
        calls["credentials_path"] = credentials_path
        calls["host_path"] = host_credentials_path
        return "token", "proj"

    monkeypatch.setattr("app.ai.verify_keys._get_vertex_auth_context", _fake_auth_context)
    monkeypatch.setattr("app.ai.verify_keys.httpx.AsyncClient", _RecordingAsyncClient)

    ok = await verify_google_key(
        "",
        project_id="proj",
        model_id="gemini-3-flash-preview",
        location="europe-west2",
        host_credentials_path="/tmp/sa.json",
    )

    assert ok is True
    assert calls["credentials_path"] == ""
    assert calls["host_path"] == "/tmp/sa.json"
    assert "locations/global" in str(_RecordingAsyncClient.last_url)


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
async def test_smoke_test_supported_models_returns_google_dual_provider_groups(monkeypatch) -> None:
    async def _anthropic(api_key: str, model_id: str) -> bool:
        return model_id == "claude-haiku-4-5"

    async def _openai(api_key: str, model_id: str) -> bool:
        return model_id == "gpt-5-mini"

    async def _google_aistudio(api_key: str, model_id: str) -> bool:
        return model_id == "gemini-3.1-pro-preview"

    async def _google_vertex(credentials_path: str, model_id: str, **kwargs) -> bool:
        return model_id == "gemini-3-flash-preview"

    monkeypatch.setattr("app.ai.verify_keys.verify_anthropic_key", _anthropic)
    monkeypatch.setattr("app.ai.verify_keys.verify_openai_key", _openai)
    monkeypatch.setattr("app.ai.verify_keys.verify_google_ai_studio_key", _google_aistudio)
    monkeypatch.setattr("app.ai.verify_keys.verify_google_key", _google_vertex)

    result = await smoke_test_supported_models(
        anthropic_key="ant",
        openai_key="open",
        google_api_key="AIza-test",
        google_credentials_path="/tmp/sa.json",
        google_project_id="proj",
        google_location="europe-west2",
    )

    assert result["llm"]["anthropic"]["ready"] is True
    assert result["llm"]["anthropic"]["available_models"] == ["claude-haiku-4-5"]
    assert result["llm"]["openai"]["ready"] is True
    assert result["llm"]["openai"]["available_models"] == ["gpt-5-mini"]

    assert result["llm"][GOOGLE_AI_STUDIO_PROVIDER]["transport"] == "aistudio"
    assert result["llm"][GOOGLE_AI_STUDIO_PROVIDER]["available_models"] == [
        "gemini-3.1-pro-preview"
    ]
    assert result["llm"][GOOGLE_VERTEX_PROVIDER]["transport"] == "vertex"
    assert result["llm"][GOOGLE_VERTEX_PROVIDER]["available_models"] == [
        "gemini-3-flash-preview"
    ]


@pytest.mark.asyncio
async def test_smoke_test_supported_models_handles_missing_google_credentials() -> None:
    result = await smoke_test_supported_models(
        google_api_key="",
        google_credentials_path="",
        google_credentials_host_path="",
    )

    assert result["llm"][GOOGLE_AI_STUDIO_PROVIDER]["ready"] is False
    assert result["llm"][GOOGLE_VERTEX_PROVIDER]["ready"] is False
    assert "reason" in result["llm"][GOOGLE_AI_STUDIO_PROVIDER]
    assert "reason" in result["llm"][GOOGLE_VERTEX_PROVIDER]
