"""Google Gemini LLM provider with streaming and precise token usage."""

import asyncio
import json
import logging
from typing import AsyncIterator

import httpx

from app.ai.llm_base import LLMError, LLMMessage, LLMProvider, LLMUsage

logger = logging.getLogger(__name__)

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_MODEL = "gemini-3-pro-preview"


class GoogleGeminiProvider(LLMProvider):
    def __init__(self, api_key: str):
        super().__init__()
        self.api_key = api_key

    async def generate_stream(
        self,
        system_prompt: str,
        messages: list[LLMMessage],
        max_tokens: int = 8192,
    ) -> AsyncIterator[str]:
        """Stream tokens from the Gemini API via SSE.

        Captures usageMetadata from SSE chunks for precise token counts.
        """
        self.last_usage = LLMUsage()
        url = f"{GEMINI_API_BASE}/{GEMINI_MODEL}:streamGenerateContent?alt=sse&key={self.api_key}"

        contents = []
        for msg in messages:
            role = "model" if msg["role"] == "assistant" else "user"
            contents.append({
                "role": role,
                "parts": self._to_gemini_parts(msg["content"]),
            })

        payload = {
            "systemInstruction": {
                "parts": [{"text": system_prompt}],
            },
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": max_tokens,
            },
        }

        retries = 3
        backoff = 1

        for attempt in range(retries):
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    async with client.stream(
                        "POST", url, json=payload,
                        headers={"Content-Type": "application/json"},
                    ) as response:
                        if response.status_code == 429 or response.status_code >= 500:
                            if attempt < retries - 1:
                                logger.warning(
                                    "Gemini API returned %d, retrying in %ds",
                                    response.status_code,
                                    backoff,
                                )
                                await asyncio.sleep(backoff)
                                backoff *= 2
                                continue
                            raise LLMError(
                                f"Gemini API error {response.status_code} after {retries} retries"
                            )

                        if response.status_code != 200:
                            body = await response.aread()
                            raise LLMError(
                                f"Gemini API error {response.status_code}: {body.decode()}"
                            )

                        async for line in response.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            data_str = line[6:]
                            try:
                                event = json.loads(data_str)
                            except json.JSONDecodeError:
                                continue

                            # Capture usage metadata (present in each chunk;
                            # the last chunk has the final counts).
                            usage_meta = event.get("usageMetadata")
                            if usage_meta:
                                self.last_usage.input_tokens = usage_meta.get(
                                    "promptTokenCount", self.last_usage.input_tokens
                                )
                                self.last_usage.output_tokens = usage_meta.get(
                                    "candidatesTokenCount", self.last_usage.output_tokens
                                )

                            candidates = event.get("candidates", [])
                            if candidates:
                                parts = (
                                    candidates[0]
                                    .get("content", {})
                                    .get("parts", [])
                                )
                                for part in parts:
                                    text = part.get("text", "")
                                    if text:
                                        yield text
                        return

            except httpx.TimeoutException:
                if attempt < retries - 1:
                    logger.warning("Gemini API timeout, retrying in %ds", backoff)
                    await asyncio.sleep(backoff)
                    backoff *= 2
                    continue
                raise LLMError("Gemini API timeout after retries")
            except LLMError:
                raise
            except Exception as e:
                raise LLMError(f"Gemini API unexpected error: {e}")

    @staticmethod
    def _to_gemini_parts(content: str | list[dict[str, str]]) -> list[dict]:
        if isinstance(content, str):
            return [{"text": content}]

        parts: list[dict] = []
        for part in content:
            if part.get("type") == "text":
                parts.append({"text": part.get("text", "")})
            elif part.get("type") == "image":
                parts.append(
                    {
                        "inline_data": {
                            "mime_type": part.get("media_type", "image/png"),
                            "data": part.get("data", ""),
                        }
                    }
                )
        return parts or [{"text": ""}]
