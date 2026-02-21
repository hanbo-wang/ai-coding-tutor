"""Anthropic Claude LLM provider with streaming and precise token usage."""

import asyncio
import json
import logging
from typing import AsyncIterator

import httpx

from app.ai.llm_base import LLMError, LLMMessage, LLMProvider, LLMUsage

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL = "claude-sonnet-4-5-20250929"


class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str):
        super().__init__()
        self.api_key = api_key

    async def generate_stream(
        self,
        system_prompt: str,
        messages: list[LLMMessage],
        max_tokens: int = 8192,
    ) -> AsyncIterator[str]:
        """Stream tokens from Claude via the Anthropic Messages API.

        Captures precise token usage from the message_start and
        message_delta SSE events.
        """
        self.last_usage = LLMUsage()
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": ANTHROPIC_MODEL,
            "max_tokens": max_tokens,
            "system": system_prompt,
            "messages": [
                {
                    "role": msg["role"],
                    "content": self._to_anthropic_content(msg["content"]),
                }
                for msg in messages
            ],
            "stream": True,
        }

        retries = 3
        backoff = 1

        for attempt in range(retries):
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    async with client.stream(
                        "POST", ANTHROPIC_API_URL, json=payload, headers=headers
                    ) as response:
                        if response.status_code == 429 or response.status_code >= 500:
                            if attempt < retries - 1:
                                logger.warning(
                                    "Anthropic API returned %d, retrying in %ds",
                                    response.status_code,
                                    backoff,
                                )
                                await asyncio.sleep(backoff)
                                backoff *= 2
                                continue
                            raise LLMError(
                                f"Anthropic API error {response.status_code} after {retries} retries"
                            )

                        if response.status_code != 200:
                            body = await response.aread()
                            raise LLMError(
                                f"Anthropic API error {response.status_code}: {body.decode()}"
                            )

                        async for line in response.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            data_str = line[6:]
                            if data_str.strip() == "[DONE]":
                                break
                            try:
                                event = json.loads(data_str)
                            except json.JSONDecodeError:
                                continue

                            event_type = event.get("type")

                            # message_start contains input token count.
                            if event_type == "message_start":
                                usage = event.get("message", {}).get("usage", {})
                                self.last_usage.input_tokens = usage.get("input_tokens", 0)

                            # content_block_delta contains streamed text.
                            elif event_type == "content_block_delta":
                                delta = event.get("delta", {})
                                text = delta.get("text", "")
                                if text:
                                    yield text

                            # message_delta contains output token count.
                            elif event_type == "message_delta":
                                usage = event.get("usage", {})
                                self.last_usage.output_tokens = usage.get("output_tokens", 0)

                        return

            except httpx.TimeoutException:
                if attempt < retries - 1:
                    logger.warning("Anthropic API timeout, retrying in %ds", backoff)
                    await asyncio.sleep(backoff)
                    backoff *= 2
                    continue
                raise LLMError("Anthropic API timeout after retries")
            except LLMError:
                raise
            except Exception as e:
                raise LLMError(f"Anthropic API unexpected error: {e}")

    @staticmethod
    def _to_anthropic_content(content: str | list[dict[str, str]]) -> list[dict]:
        if isinstance(content, str):
            return [{"type": "text", "text": content}]

        blocks: list[dict] = []
        for part in content:
            if part.get("type") == "text":
                blocks.append({"type": "text", "text": part.get("text", "")})
            elif part.get("type") == "image":
                blocks.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": part.get("media_type", "image/png"),
                            "data": part.get("data", ""),
                        },
                    }
                )
        return blocks or [{"type": "text", "text": ""}]
