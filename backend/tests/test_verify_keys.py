"""AI provider verification mapping tests."""

import pytest

from app.ai.verify_keys import verify_all_keys


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
