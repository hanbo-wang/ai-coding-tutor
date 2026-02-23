"""Health AI endpoint helper tests."""

import pytest

from app.routers import health as health_router


@pytest.mark.asyncio
async def test_ai_health_check_includes_vertex_embedding_and_caches(monkeypatch) -> None:
    calls = {"count": 0}

    async def _fake_verify_all_keys(*args, **kwargs):
        calls["count"] += 1
        return {
            "anthropic": False,
            "openai": True,
            "google": True,
            "vertex_embedding": True,
            "cohere": True,
            "voyageai": False,
        }

    monkeypatch.setattr("app.routers.health.verify_all_keys", _fake_verify_all_keys)
    health_router._last_ai_health_result = None
    health_router._last_ai_health_at = None

    first = await health_router.ai_health_check(force=True)
    second = await health_router.ai_health_check(force=False)

    assert first["vertex_embedding"] is True
    assert first["cached"] is False
    assert second["vertex_embedding"] is True
    assert second["cached"] is True
    assert calls["count"] == 1
