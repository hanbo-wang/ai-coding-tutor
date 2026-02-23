"""Google Vertex Gemini LLM provider with streaming and precise token usage."""

import asyncio
import json
import logging
from typing import AsyncIterator

import httpx

from app.ai.google_auth import GoogleServiceAccountTokenProvider
from app.ai.llm_base import LLMError, LLMMessage, LLMProvider, LLMUsage

logger = logging.getLogger(__name__)


class GoogleGeminiProvider(LLMProvider):
    def __init__(
        self,
        token_provider: GoogleServiceAccountTokenProvider,
        project_id: str,
        location: str,
        model_id: str,
    ):
        super().__init__()
        self.provider_id = "google"
        self.model_id = model_id
        self._token_provider = token_provider
        self._project_id = project_id
        self._location = location

    def _build_stream_url(self) -> str:
        host = (
            "aiplatform.googleapis.com"
            if self._location == "global"
            else f"{self._location}-aiplatform.googleapis.com"
        )
        return (
            f"https://{host}/v1/"
            f"projects/{self._project_id}/locations/{self._location}/publishers/google/"
            f"models/{self.model_id}:streamGenerateContent?alt=sse"
        )

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
        url = self._build_stream_url()

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
                access_token = await self._token_provider.get_access_token()
                async with httpx.AsyncClient(timeout=60.0) as client:
                    async with client.stream(
                        "POST",
                        url,
                        json=payload,
                        headers={
                            "Content-Type": "application/json",
                            "Authorization": f"Bearer {access_token}",
                        },
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
                                if isinstance(usage_meta, dict):
                                    self.last_usage.usage_details = {
                                        "promptTokensDetails": usage_meta.get(
                                            "promptTokensDetails"
                                        ),
                                        "candidatesTokensDetails": usage_meta.get(
                                            "candidatesTokensDetails"
                                        ),
                                        "usageMetadata": usage_meta,
                                    }

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
