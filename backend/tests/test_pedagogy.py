"""Pedagogy engine unit tests."""

import pytest

from app.ai.pedagogy_engine import PedagogyEngine, StudentState, ProcessResult


class FakeEmbeddingService:
    """Controllable embedding service for testing."""

    def __init__(self) -> None:
        self.greeting_result = False
        self.off_topic_result = False
        self.same_problem_result = False
        self.elaboration_result = False

    async def embed_text(self, text: str):
        return [0.1] * 256

    def check_greeting(self, embedding):
        return self.greeting_result

    def check_off_topic(self, embedding):
        return self.off_topic_result

    def check_same_problem(self, current, previous):
        return self.same_problem_result

    def check_elaboration_request(self, embedding):
        return self.elaboration_result

    def combine_embeddings(self, vectors):
        if not vectors:
            return None
        return vectors[0]


class FakeLLM:
    """Minimal LLM mock for difficulty classification."""

    def __init__(self):
        from app.ai.llm_base import LLMUsage
        self.last_usage = LLMUsage()

    async def generate_stream(self, system_prompt, messages, max_tokens=2048):
        yield '{"programming": 3, "maths": 3}'
        self.last_usage.input_tokens = 10
        self.last_usage.output_tokens = 5

    def count_tokens(self, text):
        return max(1, len(text) // 4)


def _make_engine(embedding_service=None):
    es = embedding_service or FakeEmbeddingService()
    return PedagogyEngine(es, FakeLLM())


def _make_state(prog=3.0, maths=3.0):
    return StudentState(
        user_id="test-user",
        effective_programming_level=prog,
        effective_maths_level=maths,
    )


@pytest.mark.asyncio
async def test_greeting_returns_canned_response() -> None:
    """Greeting detection should return a canned response with the username."""
    es = FakeEmbeddingService()
    es.greeting_result = True
    engine = _make_engine(es)
    state = _make_state()

    result = await engine.process_message(
        "hello",
        state,
        username="Alice",
        enable_greeting_filter=True,
    )
    assert result.filter_result == "greeting"
    assert "Alice" in (result.canned_response or "")


@pytest.mark.asyncio
async def test_off_topic_returns_rejection() -> None:
    """Off topic detection should return a rejection."""
    es = FakeEmbeddingService()
    es.off_topic_result = True
    engine = _make_engine(es)
    state = _make_state()

    result = await engine.process_message(
        "what is the weather?",
        state,
        username="Bob",
        enable_off_topic_filter=True,
    )
    assert result.filter_result == "off_topic"


@pytest.mark.asyncio
async def test_topic_filters_disabled_by_default() -> None:
    """Greeting and off-topic checks should be disabled unless explicitly enabled."""
    es = FakeEmbeddingService()
    es.greeting_result = True
    es.off_topic_result = True
    engine = _make_engine(es)
    state = _make_state()

    result = await engine.process_message("hello", state, username="Alice")
    assert result.filter_result is None


@pytest.mark.asyncio
async def test_hint_escalation() -> None:
    """5 same problem messages should produce hint levels 1, 2, 3, 4, 5."""
    es = FakeEmbeddingService()
    es.same_problem_result = True
    engine = _make_engine(es)
    state = _make_state()

    levels = []
    for i in range(5):
        # First message is always new problem (no previous context).
        if i == 0:
            es.same_problem_result = False
        else:
            es.same_problem_result = True

        result = await engine.process_message(f"question {i}", state, username="Alice")
        if not result.filter_result:
            levels.append(result.hint_level)
            # Simulate context update.
            state.last_context_embedding = [0.1] * 256

    assert levels == [1, 2, 3, 4, 5]


@pytest.mark.asyncio
async def test_hint_cap_at_five() -> None:
    """Hint level should not exceed 5."""
    es = FakeEmbeddingService()
    engine = _make_engine(es)
    state = _make_state()
    state.current_hint_level = 5
    state.last_context_embedding = [0.1] * 256

    es.same_problem_result = True
    result = await engine.process_message("more help please", state, username="Alice")
    assert result.hint_level == 5


@pytest.mark.asyncio
async def test_hint_reset_on_new_problem() -> None:
    """A new problem should reset hint level from a higher follow-up state."""
    es = FakeEmbeddingService()
    engine = _make_engine(es)
    state = _make_state()
    state.current_hint_level = 4
    state.current_programming_difficulty = 4
    state.current_maths_difficulty = 4
    state.last_context_embedding = [0.1] * 256

    es.same_problem_result = False
    es.elaboration_result = False

    result = await engine.process_message("new topic question", state, username="Alice")
    assert result.is_same_problem is False
    assert result.hint_level == 1


def test_ema_level_update() -> None:
    """EMA update with difficulty 4, hint 2 on level 3.0 should produce 3.04."""
    state = _make_state(prog=3.0, maths=3.0)

    # Set the state fields that _update_effective_levels reads.
    state.current_programming_difficulty = 4
    state.current_maths_difficulty = 3
    state.current_hint_level = 2

    PedagogyEngine._update_effective_levels(state)

    # demonstrated_prog = 4 * (6 - 2) / 5 = 3.2
    # rate = 0.2 * min(1, 4/3.0) = 0.2
    # new = 3.0 * 0.8 + 3.2 * 0.2 = 3.04
    assert abs(state.effective_programming_level - 3.04) < 0.01
