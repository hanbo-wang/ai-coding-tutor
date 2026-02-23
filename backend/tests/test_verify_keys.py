"""AI provider verification tests."""

import pytest

from app.ai.verify_keys import verify_all_keys, verify_google_key


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
        google_credentials_path="/tmp/sa.json",
        google_project_id="proj",
        cohere_key="c",
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


class _FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "ok") -> None:
        self.status_code = status_code
        self.text = text


class _RecordingAsyncClient:
    last_url: str | None = None

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, headers=None, json=None):
        _RecordingAsyncClient.last_url = url
        return _FakeResponse(200)


@pytest.mark.asyncio
async def test_verify_google_key_uses_global_vertex_host(monkeypatch) -> None:
    async def _fake_auth_context(credentials_path: str, explicit_project_id: str = ""):
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
