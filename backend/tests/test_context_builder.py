"""Context builder unit tests."""

import pytest

from app.ai.context_builder import build_context_messages
from tests.conftest import MockLLMProvider


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
