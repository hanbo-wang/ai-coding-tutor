"""Context builder unit tests."""

import pytest

from app.ai.context_builder import build_context_messages
from tests.conftest import MockLLMProvider


class CountingMockLLM(MockLLMProvider):
    def __init__(self) -> None:
        super().__init__()
        self.generate_stream_calls = 0

    async def generate_stream(self, system_prompt, messages, max_tokens=2048):
        self.generate_stream_calls += 1
        async for token in super().generate_stream(system_prompt, messages, max_tokens):
            yield token


@pytest.mark.asyncio
async def test_empty_history() -> None:
    """Empty history should return only the current user message."""
    llm = MockLLMProvider()
    messages = await build_context_messages(
        chat_history=[],
        user_message="Hello",
        llm=llm,
        max_context_tokens=10000,
    )
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "Hello"


@pytest.mark.asyncio
async def test_token_budget_truncation() -> None:
    """History exceeding the token budget should be truncated to fit."""
    llm = MockLLMProvider()
    # Create 50 messages that will exceed any small budget.
    history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"Message {i} " * 20}
        for i in range(50)
    ]
    messages = await build_context_messages(
        chat_history=history,
        user_message="New question",
        llm=llm,
        max_context_tokens=100,
    )
    # Should have fewer messages than the original history plus current.
    assert len(messages) < 52
    # The last message should be the current user message.
    assert messages[-1]["content"] == "New question"


@pytest.mark.asyncio
async def test_full_history_within_budget() -> None:
    """Short history within budget should be included in full."""
    llm = MockLLMProvider()
    history = [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hello!"},
    ]
    messages = await build_context_messages(
        chat_history=history,
        user_message="Follow up",
        llm=llm,
        max_context_tokens=10000,
    )
    assert len(messages) == 3
    assert messages[0]["content"] == "Hi"
    assert messages[1]["content"] == "Hello!"
    assert messages[2]["content"] == "Follow up"


@pytest.mark.asyncio
async def test_uses_cached_summary_without_inline_compression() -> None:
    """A valid cached summary should be used without calling the compression LLM path."""
    llm = CountingMockLLM()
    history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"Message {i} " * 30}
        for i in range(30)
    ]
    messages = await build_context_messages(
        chat_history=history,
        user_message="Current question",
        llm=llm,
        max_context_tokens=120,
        cached_summary="We discussed loops and debugging strategy.",
        cached_summary_message_count=20,
        allow_inline_compression=False,
    )
    assert messages[-1]["content"] == "Current question"
    assert messages[0]["content"].startswith("[Earlier conversation summary]")
    assert llm.generate_stream_calls == 0


@pytest.mark.asyncio
async def test_no_cache_and_no_inline_compression_falls_back_to_truncation() -> None:
    """When inline compression is disabled, the builder should truncate without LLM summarisation."""
    llm = CountingMockLLM()
    history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"Message {i} " * 30}
        for i in range(30)
    ]
    messages = await build_context_messages(
        chat_history=history,
        user_message="Current question",
        llm=llm,
        max_context_tokens=120,
        allow_inline_compression=False,
    )
    assert messages[-1]["content"] == "Current question"
    assert llm.generate_stream_calls == 0
