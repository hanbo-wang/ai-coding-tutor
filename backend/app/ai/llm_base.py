"""LLM provider interface and shared types."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator

LLMContentPart = dict[str, str]
LLMMessage = dict[str, str | list[LLMContentPart]]


class LLMError(Exception):
    """Raised when an LLM provider fails unrecoverably."""
    pass


@dataclass
class LLMUsage:
    """Token usage reported by the LLM API after a call completes."""
    input_tokens: int = 0
    output_tokens: int = 0
    usage_details: dict = field(default_factory=dict)


class LLMProvider(ABC):
    """Base class for LLM providers.

    After each generate_stream() call completes, ``last_usage`` contains
    the precise input and output token counts reported by the API.
    """

    def __init__(self) -> None:
        self.last_usage: LLMUsage = LLMUsage()
        self.provider_id: str = "unknown"
        self.model_id: str = "unknown"
        # Optional runtime transport marker used by provider-specific backends.
        self.runtime_transport: str | None = None

    @abstractmethod
    async def generate_stream(
        self,
        system_prompt: str,
        messages: list[LLMMessage],
        max_tokens: int = 8192,
    ) -> AsyncIterator[str]:
        """Yield response tokens one at a time.

        Implementations must populate ``self.last_usage`` with the precise
        token counts reported by the API before returning.
        """
        ...

    async def generate(
        self,
        system_prompt: str,
        messages: list[LLMMessage],
        max_tokens: int = 30,
    ) -> str:
        """Non-streaming generation. Collects output from generate_stream."""
        parts: list[str] = []
        async for chunk in self.generate_stream(system_prompt, messages, max_tokens):
            parts.append(chunk)
        return "".join(parts)

    def count_tokens(self, text: str) -> int:
        """Return an approximate token count for pre-call budget estimation.

        This is used only for context window budgeting and input guards
        before the API is called. Precise counts come from ``last_usage``
        after the call completes.
        """
        return max(1, len(text) // 4)
