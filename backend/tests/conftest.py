"""Shared test fixtures and mock implementations."""

from typing import AsyncIterator

from app.ai.llm_base import LLMProvider, LLMUsage


class MockLLMProvider(LLMProvider):
    """Mock LLM provider that yields predetermined tokens.

    Sets last_usage with configurable precise token counts after streaming.
    """

    def __init__(
        self,
        tokens: list[str] | None = None,
        input_tokens: int = 10,
        output_tokens: int = 5,
    ) -> None:
        super().__init__()
        self.tokens = tokens or ["Hello", " ", "world"]
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens

    async def generate_stream(
        self,
        system_prompt: str,
        messages: list[dict],
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]:
        self.last_usage = LLMUsage()
        for token in self.tokens:
            yield token
        # Simulate precise usage from the API.
        self.last_usage.input_tokens = self._input_tokens
        self.last_usage.output_tokens = self._output_tokens
