"""OpenAI provider tests."""

from __future__ import annotations

import json

import pytest

from app.ai.llm_openai import OpenAIProvider


class _FakeResponse:
    def __init__(self) -> None:
        self.status_code = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def aiter_lines(self):
        yield 'data: {"choices":[{"delta":{"content":"Hi"}}]}'
        yield (
            "data: "
            + json.dumps(
                {
                    "choices": [{"delta": {"content": "!"}}],
                    "usage": {"prompt_tokens": 7, "completion_tokens": 2},
                }
            )
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
async def test_openai_stream_uses_selected_model_and_parses_usage(monkeypatch) -> None:
    monkeypatch.setattr("app.ai.llm_openai.httpx.AsyncClient", _FakeAsyncClient)
    provider = OpenAIProvider("sk-test", model_id="gpt-5-mini")

    chunks = []
    async for chunk in provider.generate_stream(
        system_prompt="Test",
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=9,
    ):
        chunks.append(chunk)

    assert "".join(chunks) == "Hi!"
    assert provider.last_usage.input_tokens == 7
    assert provider.last_usage.output_tokens == 2
    call = _FakeAsyncClient.last_call or {}
    assert call["url"].endswith("/v1/chat/completions")
    assert call["json"]["model"] == "gpt-5-mini"
    assert call["json"]["max_completion_tokens"] == 9
