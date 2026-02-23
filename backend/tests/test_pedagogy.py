"""Pedagogy engine unit tests for the current streaming metadata paths."""

import pytest

from app.ai.pedagogy_engine import (
    PedagogyEngine,
    PedagogyFastSignals,
    StudentState,
    StreamPedagogyMeta,
)
from app.ai.llm_base import LLMUsage


class FakeEmbeddingService:
    """Controllable embedding service for testing."""

    def __init__(self) -> None:
        self.greeting_result = False
        self.off_topic_result = False
        self.same_problem_result = False
        self.elaboration_result = False
        self.next_embedding = [0.1] * 256

    async def embed_text(self, text: str):
        return self.next_embedding

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
        # Return a distinct marker so tests can verify the combine path.
        return [0.9] * len(vectors[0])


class FakeLLM:
    """Minimal LLM mock for merged preflight metadata classification."""

    def __init__(self) -> None:
        self.last_usage = LLMUsage()
        self.preflight_same_problem = False
        self.preflight_is_elaboration = False
        self.preflight_programming_difficulty = 3
        self.preflight_maths_difficulty = 3
        self.preflight_hint_level = 2
        self.call_kinds: list[str] = []

    async def generate_stream(self, system_prompt, messages, max_tokens=2048):
        self.call_kinds.append("preflight")
        yield (
            '{"same_problem": '
            f'{"true" if self.preflight_same_problem else "false"}, '
            '"is_elaboration": '
            f'{"true" if self.preflight_is_elaboration else "false"}, '
            '"programming_difficulty": '
            f"{self.preflight_programming_difficulty}, "
            '"maths_difficulty": '
            f"{self.preflight_maths_difficulty}, "
            '"hint_level": '
            f"{self.preflight_hint_level}"
            "}"
        )
        self.last_usage.input_tokens = 10
        self.last_usage.output_tokens = 5

    async def generate(self, system_prompt, messages, max_tokens=30):
        parts = []
        async for chunk in self.generate_stream(system_prompt, messages, max_tokens):
            parts.append(chunk)
        return "".join(parts)

    def count_tokens(self, text):
        return max(1, len(text) // 4)


def _make_engine(embedding_service=None, llm=None):
    es = embedding_service or FakeEmbeddingService()
    llm = llm or FakeLLM()
    return PedagogyEngine(es, llm)


def _make_state(prog=3.0, maths=3.0):
    return StudentState(
        user_id="test-user",
        effective_programming_level=prog,
        effective_maths_level=maths,
    )


@pytest.mark.asyncio
async def test_prepare_fast_signals_returns_greeting_canned_response() -> None:
    """Greeting detection should return a canned response with the username."""
    es = FakeEmbeddingService()
    es.greeting_result = True
    engine = _make_engine(es)
    state = _make_state()

    signals = await engine.prepare_fast_signals(
        "hello",
        state,
        username="Alice",
        enable_greeting_filter=True,
    )

    assert signals.filter_result == "greeting"
    assert "Alice" in (signals.canned_response or "")


@pytest.mark.asyncio
async def test_prepare_fast_signals_returns_off_topic_canned_response() -> None:
    """Off-topic detection should return a canned response."""
    es = FakeEmbeddingService()
    es.off_topic_result = True
    engine = _make_engine(es)
    state = _make_state()

    signals = await engine.prepare_fast_signals(
        "what is the weather?",
        state,
        username="Bob",
        enable_off_topic_filter=True,
    )

    assert signals.filter_result == "off_topic"
    assert "programming" in (signals.canned_response or "")


@pytest.mark.asyncio
async def test_prepare_fast_signals_derives_elaboration_from_embedding() -> None:
    """Embedding elaboration anchors should set same-problem and elaboration signals."""
    es = FakeEmbeddingService()
    es.elaboration_result = True
    engine = _make_engine(es)
    state = _make_state()
    state.last_context_embedding = [0.1] * 256
    state.last_question_text = "Implement binary search"
    state.last_answer_text = "Check the middle element and halve the interval."

    signals = await engine.prepare_fast_signals("Explain more", state)

    assert signals.embedding_same_problem is True
    assert signals.embedding_is_elaboration is True
    assert signals.has_previous_exchange is True
    assert signals.previous_question_text == "Implement binary search"


def test_coerce_stream_meta_clamps_and_normalises() -> None:
    """Stream metadata should be parsed, clamped, and normalised safely."""
    engine = _make_engine()
    state = _make_state()
    state.last_context_embedding = [0.1] * 256
    state.last_question_text = "Previous question"
    state.last_answer_text = "Previous answer"
    signals = PedagogyFastSignals(
        embedding_same_problem=True,
        embedding_is_elaboration=True,
        has_previous_exchange=True,
        previous_question_text=state.last_question_text,
        previous_answer_text=state.last_answer_text,
    )

    meta = engine.coerce_stream_meta(
        {
            "same_problem": "true",
            "is_elaboration": "true",
            "programming_difficulty": "9",
            "maths_difficulty": 0,
            "hint_level": "6",
        },
        student_state=state,
        fast_signals=signals,
    )

    assert meta.same_problem is True
    assert meta.is_elaboration is True
    assert meta.programming_difficulty == 5
    assert meta.maths_difficulty == 1
    assert meta.hint_level == 5


def test_coerce_stream_meta_forces_new_problem_without_previous_context() -> None:
    """Metadata cannot claim same-problem when no previous context exists."""
    engine = _make_engine()
    state = _make_state()
    signals = PedagogyFastSignals(
        embedding_same_problem=True,
        embedding_is_elaboration=True,
        has_previous_exchange=False,
    )

    meta = engine.coerce_stream_meta(
        {
            "same_problem": True,
            "is_elaboration": True,
            "programming_difficulty": 3,
            "maths_difficulty": 2,
            "hint_level": 2,
        },
        student_state=state,
        fast_signals=signals,
    )

    assert meta.same_problem is False
    assert meta.is_elaboration is False


def test_build_fallback_stream_meta_uses_embedding_signal() -> None:
    """Fallback metadata should use embedding signals and current state."""
    engine = _make_engine()
    state = _make_state()
    state.current_hint_level = 2
    state.current_programming_difficulty = 4
    state.current_maths_difficulty = 2
    state.last_context_embedding = [0.1] * 256
    signals = PedagogyFastSignals(
        embedding_same_problem=True,
        embedding_is_elaboration=False,
        has_previous_exchange=True,
        previous_question_text="Q",
        previous_answer_text="A",
    )

    meta = engine.build_fallback_stream_meta(state, signals)

    assert meta.source == "fallback"
    assert meta.same_problem is True
    assert meta.hint_level == 3
    assert meta.programming_difficulty == 4
    assert meta.maths_difficulty == 2


def test_apply_stream_meta_updates_state_for_new_problem() -> None:
    """Applying new-problem metadata should update current levels and starting hint."""
    engine = _make_engine()
    state = _make_state()
    state.current_hint_level = 4
    state.current_programming_difficulty = 4
    state.current_maths_difficulty = 3
    state.last_context_embedding = [0.1] * 256
    state.last_question_text = "old"
    state.last_answer_text = "old answer"

    result = engine.apply_stream_meta(
        state,
        StreamPedagogyMeta(
            same_problem=False,
            is_elaboration=False,
            programming_difficulty=2,
            maths_difficulty=2,
            hint_level=1,
        ),
    )

    assert result.is_same_problem is False
    assert state.current_hint_level == 1
    assert state.current_programming_difficulty == 2
    assert state.current_maths_difficulty == 2
    assert state.starting_hint_level == 1


@pytest.mark.asyncio
async def test_classify_preflight_meta_returns_validated_metadata() -> None:
    """Merged preflight should return validated metadata in one LLM call."""
    es = FakeEmbeddingService()
    llm = FakeLLM()
    llm.preflight_same_problem = True
    llm.preflight_is_elaboration = True
    llm.preflight_programming_difficulty = 4
    llm.preflight_maths_difficulty = 2
    llm.preflight_hint_level = 3
    engine = _make_engine(es, llm=llm)
    state = _make_state()
    state.current_hint_level = 2
    state.current_programming_difficulty = 3
    state.current_maths_difficulty = 2
    state.last_context_embedding = [0.1] * 256
    state.last_question_text = "Implement binary search"
    state.last_answer_text = "Check the middle element."
    signals = await engine.prepare_fast_signals("Why does this work?", state)

    meta = await engine.classify_preflight_meta(
        "Why does this work?",
        student_state=state,
        fast_signals=signals,
    )

    assert meta.source == "preflight"
    assert meta.same_problem is True
    assert meta.is_elaboration is True
    assert meta.programming_difficulty == 4
    assert meta.maths_difficulty == 2
    assert meta.hint_level == 3
    assert llm.call_kinds == ["preflight"]


@pytest.mark.asyncio
async def test_classify_preflight_meta_falls_back_on_invalid_payload() -> None:
    """Invalid preflight JSON should fall back to embedding/state-derived metadata."""
    es = FakeEmbeddingService()
    es.same_problem_result = True

    class BadPreflightLLM(FakeLLM):
        async def generate_stream(self, system_prompt, messages, max_tokens=2048):
            self.call_kinds.append("preflight")
            yield '{"same_problem": true, "oops": 1}'
            self.last_usage.input_tokens = 10
            self.last_usage.output_tokens = 3

    llm = BadPreflightLLM()
    engine = _make_engine(es, llm=llm)
    state = _make_state()
    state.current_hint_level = 2
    state.current_programming_difficulty = 4
    state.current_maths_difficulty = 3
    state.last_context_embedding = [0.1] * 256
    state.last_question_text = "Previous question"
    state.last_answer_text = "Previous answer"
    signals = await engine.prepare_fast_signals("Explain more", state)

    meta = await engine.classify_preflight_meta(
        "Explain more",
        student_state=state,
        fast_signals=signals,
    )

    assert meta.source == "fallback"
    assert meta.same_problem is True
    assert meta.hint_level == 3


@pytest.mark.asyncio
async def test_preflight_payload_truncates_current_message_for_latency() -> None:
    """The merged preflight payload should trim long current messages to stay lightweight."""
    llm = FakeLLM()
    engine = _make_engine(llm=llm)
    state = _make_state()
    signals = PedagogyFastSignals()
    long_message = "token " * 2000

    payload = engine._build_preflight_payload(
        user_message=long_message,
        student_state=state,
        fast_signals=signals,
    )

    current_message = str(payload["current_message"])
    assert llm.count_tokens(current_message) <= 320
    assert current_message


@pytest.mark.asyncio
async def test_update_context_embedding_stores_combined_embedding_and_text() -> None:
    """Q+A context should be embedded and stored for the next turn."""
    es = FakeEmbeddingService()
    engine = _make_engine(es)
    state = _make_state()

    await engine.update_context_embedding(
        state,
        question="What is recursion?",
        answer="A function can call itself.",
        question_embedding=[0.1] * 256,
    )

    assert state.last_context_embedding is not None
    assert state.last_context_embedding[0] == pytest.approx(0.9)
    assert state.last_question_text == "What is recursion?"
    assert state.last_answer_text == "A function can call itself."


def test_ema_level_update() -> None:
    """EMA update with difficulty 4, hint 2 on level 3.0 should produce 3.04."""
    state = _make_state(prog=3.0, maths=3.0)

    state.current_programming_difficulty = 4
    state.current_maths_difficulty = 3
    state.current_hint_level = 2

    PedagogyEngine._update_effective_levels(state)

    assert abs(state.effective_programming_level - 3.04) < 0.01

