"""Google AI Studio Gemini API provider tests."""

from __future__ import annotations

import json

import pytest

from app.ai.llm_google import GoogleGeminiAIStudioProvider


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
                'data: {"candidates":[{"content":{"parts":[{"text":"Pro"}]}}]}',
                (
                    'data: '
                    + json.dumps(
                        {
                            "candidates": [{"content": {"parts": [{"text": "ng"}]}}],
                            "usageMetadata": {
                                "promptTokenCount": 20,
                                "candidatesTokenCount": 7,
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
async def test_ai_studio_gemini_stream_parses_text_and_usage(monkeypatch) -> None:
    monkeypatch.setattr("app.ai.llm_google.httpx.AsyncClient", _FakeAsyncClient)

    provider = GoogleGeminiAIStudioProvider(
        api_key="AIza-test-key",
        model_id="gemini-3.1-pro-preview",
    )

    chunks: list[str] = []
    async for chunk in provider.generate_stream(
        system_prompt="Reply briefly.",
        messages=[{"role": "user", "content": "ping"}],
        max_tokens=16,
    ):
        chunks.append(chunk)

    assert "".join(chunks) == "Prong"
    assert provider.last_usage.input_tokens == 20
    assert provider.last_usage.output_tokens == 7

    call = _FakeAsyncClient.last_call or {}
    assert call["method"] == "POST"
    assert call["url"] == (
        "https://generativelanguage.googleapis.com/v1beta/"
        "models/gemini-3.1-pro-preview:streamGenerateContent?alt=sse"
    )
    assert call["headers"]["x-goog-api-key"] == "AIza-test-key"
    assert call["json"]["generationConfig"]["maxOutputTokens"] == 16


@pytest.mark.asyncio
async def test_ai_studio_multimodal_payload_uses_gemini_api_field_names(monkeypatch) -> None:
    monkeypatch.setattr("app.ai.llm_google.httpx.AsyncClient", _FakeAsyncClient)

    provider = GoogleGeminiAIStudioProvider(
        api_key="AIza-test-key",
        model_id="gemini-3-flash-preview",
    )

    async for _ in provider.generate_stream(
        system_prompt="Analyse the screenshot.",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is wrong here?"},
                    {
                        "type": "image",
                        "media_type": "image/png",
                        "data": "ZmFrZS1iYXNlNjQ=",
                    },
                ],
            }
        ],
        max_tokens=32,
    ):
        pass

    call = _FakeAsyncClient.last_call or {}
    payload = call["json"]
    assert "system_instruction" in payload
    assert "systemInstruction" not in payload
    parts = payload["contents"][0]["parts"]
    assert parts[0] == {"text": "What is wrong here?"}
    assert parts[1] == {
        "inline_data": {
            "mime_type": "image/png",
            "data": "ZmFrZS1iYXNlNjQ=",
        }
    }
