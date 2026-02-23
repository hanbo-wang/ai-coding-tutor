"""Google Vertex Gemini provider tests."""

from __future__ import annotations

import json

import pytest

from app.ai.llm_google import GoogleGeminiProvider


class _FakeTokenProvider:
    async def get_access_token(self) -> str:
        return "test-token"


class _FakeStreamResponse:
    def __init__(self, *, status_code: int, lines: list[str], body: str = "") -> None:
        self.status_code = status_code
        self._lines = lines
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aread(self) -> bytes:
        return self._body.encode()


class _FakeAsyncClient:
    last_call: dict | None = None

    def __init__(self, *args, **kwargs) -> None:
        self.response = _FakeStreamResponse(
            status_code=200,
            lines=[
                'data: {"candidates":[{"content":{"parts":[{"text":"Hel"}]}}]}',
                (
                    'data: '
                    + json.dumps(
                        {
                            "candidates": [{"content": {"parts": [{"text": "lo"}]}}],
                            "usageMetadata": {
                                "promptTokenCount": 12,
                                "candidatesTokenCount": 5,
                                "promptTokensDetails": [{"modality": "TEXT", "tokenCount": 12}],
                                "candidatesTokensDetails": [
                                    {"modality": "TEXT", "tokenCount": 5}
                                ],
                            },
                        }
                    )
                ),
            ],
        )

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
        return self.response


@pytest.mark.asyncio
async def test_vertex_gemini_stream_parses_text_and_usage(monkeypatch) -> None:
    monkeypatch.setattr("app.ai.llm_google.httpx.AsyncClient", _FakeAsyncClient)

    provider = GoogleGeminiProvider(
        token_provider=_FakeTokenProvider(),
        project_id="demo-proj",
        location="global",
        model_id="gemini-3-flash-preview",
    )

    chunks = []
    async for chunk in provider.generate_stream(
        system_prompt="You are helpful.",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=8,
    ):
        chunks.append(chunk)

    assert "".join(chunks) == "Hello"
    assert provider.last_usage.input_tokens == 12
    assert provider.last_usage.output_tokens == 5
    assert provider.last_usage.usage_details["promptTokensDetails"][0]["tokenCount"] == 12

    call = _FakeAsyncClient.last_call or {}
    assert call["method"] == "POST"
    assert call["url"].startswith("https://aiplatform.googleapis.com/v1/")
    assert "projects/demo-proj/locations/global" in call["url"]
    assert "models/gemini-3-flash-preview:streamGenerateContent" in call["url"]
    assert call["headers"]["Authorization"] == "Bearer test-token"
    assert call["json"]["generationConfig"]["maxOutputTokens"] == 8
