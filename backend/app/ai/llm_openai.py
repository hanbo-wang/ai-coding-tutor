"""OpenAI GPT LLM provider with streaming and precise token usage."""

import asyncio
import json
import logging
from typing import AsyncIterator

import httpx

from app.ai.llm_base import LLMError, LLMMessage, LLMProvider, LLMUsage

logger = logging.getLogger(__name__)

OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, model_id: str):
        super().__init__()
        self.provider_id = "openai"
        self.model_id = model_id
        self.api_key = api_key

    async def generate_stream(
        self,
        system_prompt: str,
        messages: list[LLMMessage],
        max_tokens: int = 8192,
    ) -> AsyncIterator[str]:
        """Stream tokens from the OpenAI Chat Completions API.

        Uses stream_options.include_usage to get precise token counts
        in the final SSE chunk.
        """
        self.last_usage = LLMUsage()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        api_messages: list[dict] = [{"role": "system", "content": system_prompt}]
        for msg in messages:
            api_messages.append({
                "role": msg["role"],
                "content": self._to_openai_content(msg["content"]),
            })

        payload = {
            "model": self.model_id,
            "max_completion_tokens": max_tokens,
            "messages": api_messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        retries = 3
        backoff = 1

        for attempt in range(retries):
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    async with client.stream(
                        "POST", OPENAI_API_URL, json=payload, headers=headers
                    ) as response:
                        if response.status_code == 429 or response.status_code >= 500:
                            if attempt < retries - 1:
                                logger.warning(
                                    "OpenAI API returned %d, retrying in %ds",
                                    response.status_code,
                                    backoff,
                                )
                                await asyncio.sleep(backoff)
                                backoff *= 2
                                continue
                            raise LLMError(
                                f"OpenAI API error {response.status_code} after {retries} retries"
                            )

                        if response.status_code != 200:
                            body = await response.aread()
                            raise LLMError(
                                f"OpenAI API error {response.status_code}: {body.decode()}"
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

                            # The final chunk with include_usage has a usage field.
                            usage = event.get("usage")
                            if usage:
                                self.last_usage.input_tokens = usage.get("prompt_tokens", 0)
                                self.last_usage.output_tokens = usage.get("completion_tokens", 0)
                                if isinstance(usage, dict):
                                    self.last_usage.usage_details = {"usage": usage}

                            choices = event.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                text = delta.get("content", "")
                                if text:
                                    yield text
                        return

            except httpx.TimeoutException:
                if attempt < retries - 1:
                    logger.warning("OpenAI API timeout, retrying in %ds", backoff)
                    await asyncio.sleep(backoff)
                    backoff *= 2
                    continue
                raise LLMError("OpenAI API timeout after retries")
            except LLMError:
                raise
            except Exception as e:
                raise LLMError(f"OpenAI API unexpected error: {e}")

    @staticmethod
    def _to_openai_content(content: str | list[dict[str, str]]) -> str | list[dict]:
        if isinstance(content, str):
            return content

        parts: list[dict] = []
        for part in content:
            if part.get("type") == "text":
                parts.append({"type": "text", "text": part.get("text", "")})
            elif part.get("type") == "image":
                media_type = part.get("media_type", "image/png")
                image_data = part.get("data", "")
                parts.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{image_data}"
                        },
                    }
                )
        return parts or [{"type": "text", "text": ""}]
