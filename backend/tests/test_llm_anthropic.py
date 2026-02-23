"""Anthropic provider tests."""

from __future__ import annotations

import json

import pytest

from app.ai.llm_anthropic import AnthropicProvider


class _FakeResponse:
    status_code = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def aiter_lines(self):
        yield (
            "data: "
            + json.dumps({"type": "message_start", "message": {"usage": {"input_tokens": 11}}})
        )
        yield (
            "data: "
            + json.dumps({"type": "content_block_delta", "delta": {"text": "OK"}})
        )
        yield (
            "data: "
            + json.dumps({"type": "message_delta", "usage": {"output_tokens": 3}})
        )
        yield "data: [DONE]"

    async def aread(self) -> bytes:
        return b""


class _FakeAsyncClient:
    last_call: dict | None = None

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def stream(self, method, url, json=None, headers=None):
        _FakeAsyncClient.last_call = {
            "method": method,
            "url": url,
            "json": json,
            "headers": headers,
        }
        return _FakeResponse()


@pytest.mark.asyncio
async def test_anthropic_stream_uses_selected_model(monkeypatch) -> None:
    monkeypatch.setattr("app.ai.llm_anthropic.httpx.AsyncClient", _FakeAsyncClient)
    provider = AnthropicProvider("ak-test", model_id="claude-haiku-4-5")

    chunks = []
    async for chunk in provider.generate_stream(
        system_prompt="Test",
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=5,
    ):
        chunks.append(chunk)

    assert "".join(chunks) == "OK"
    assert provider.last_usage.input_tokens == 11
    assert provider.last_usage.output_tokens == 3
    call = _FakeAsyncClient.last_call or {}
    assert call["json"]["model"] == "claude-haiku-4-5"
