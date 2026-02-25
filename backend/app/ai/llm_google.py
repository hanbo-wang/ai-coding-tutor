"""Google Gemini LLM providers for Vertex AI and Google AI Studio."""

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from typing import AsyncIterator

import httpx

from app.ai.google_auth import GoogleServiceAccountTokenProvider
from app.ai.llm_base import LLMError, LLMMessage, LLMProvider, LLMUsage

logger = logging.getLogger(__name__)


class _GoogleGeminiBaseProvider(LLMProvider, ABC):
    def __init__(self, *, model_id: str) -> None:
        super().__init__()
        self.provider_id = "google"
        self.model_id = model_id

    @abstractmethod
    def _build_stream_url(self) -> str:
        """Return the streaming endpoint URL."""

    @abstractmethod
    async def _build_headers(self) -> dict[str, str]:
        """Return request headers for the active transport."""

    @abstractmethod
    def _system_instruction_key(self) -> str:
        """Return the transport-specific key for system instructions."""

    @abstractmethod
    def _inline_data_key(self) -> str:
        """Return the transport-specific key for inline binary parts."""

    @abstractmethod
    def _mime_type_key(self) -> str:
        """Return the transport-specific key for MIME types inside inline data."""

    async def generate_stream(
        self,
        system_prompt: str,
        messages: list[LLMMessage],
        max_tokens: int = 8192,
    ) -> AsyncIterator[str]:
        """Stream tokens from the Gemini API via SSE and capture usage metadata."""
        self.last_usage = LLMUsage()
        url = self._build_stream_url()

        contents = []
        for msg in messages:
            role = "model" if msg["role"] == "assistant" else "user"
            contents.append(
                {
                    "role": role,
                    "parts": self._to_gemini_parts(msg["content"]),
                }
            )

        payload = {
            self._system_instruction_key(): {
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
                headers = await self._build_headers()
                async with httpx.AsyncClient(timeout=60.0) as client:
                    async with client.stream(
                        "POST",
                        url,
                        json=payload,
                        headers=headers,
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
                            if not candidates:
                                continue
                            parts = candidates[0].get("content", {}).get("parts", [])
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
            except Exception as exc:
                raise LLMError(f"Gemini API unexpected error: {exc}")

    def _to_gemini_parts(self, content: str | list[dict[str, str]]) -> list[dict]:
        if isinstance(content, str):
            return [{"text": content}]

        parts: list[dict] = []
        for part in content:
            if part.get("type") == "text":
                parts.append({"text": part.get("text", "")})
            elif part.get("type") == "image":
                parts.append(
                    {
                        self._inline_data_key(): {
                            self._mime_type_key(): part.get("media_type", "image/png"),
                            "data": part.get("data", ""),
                        }
                    }
                )
        return parts or [{"text": ""}]


class GoogleGeminiVertexProvider(_GoogleGeminiBaseProvider):
    """Gemini via Vertex AI (service account + Bearer token)."""

    def __init__(
        self,
        token_provider: GoogleServiceAccountTokenProvider,
        project_id: str,
        location: str,
        model_id: str,
    ) -> None:
        super().__init__(model_id=model_id)
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

    async def _build_headers(self) -> dict[str, str]:
        access_token = await self._token_provider.get_access_token()
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        }

    def _system_instruction_key(self) -> str:
        return "systemInstruction"

    def _inline_data_key(self) -> str:
        return "inlineData"

    def _mime_type_key(self) -> str:
        return "mimeType"


class GoogleGeminiAIStudioProvider(_GoogleGeminiBaseProvider):
    """Gemini via Google AI Studio / Gemini API (API key)."""

    def __init__(self, api_key: str, model_id: str) -> None:
        super().__init__(model_id=model_id)
        self._api_key = api_key

    def _build_stream_url(self) -> str:
        return (
            "https://generativelanguage.googleapis.com/v1beta/"
            f"models/{self.model_id}:streamGenerateContent?alt=sse"
        )

    async def _build_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-goog-api-key": self._api_key,
        }

    def _system_instruction_key(self) -> str:
        return "system_instruction"

    def _inline_data_key(self) -> str:
        return "inline_data"

    def _mime_type_key(self) -> str:
        return "mime_type"


# Backwards-compatible name used by existing code/tests for the Vertex path.
GoogleGeminiProvider = GoogleGeminiVertexProvider
