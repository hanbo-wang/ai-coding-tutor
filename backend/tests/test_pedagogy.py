"""Pedagogy engine unit tests for the current metadata routes."""

import pytest

from app.ai.llm_base import LLMUsage
from app.ai.pedagogy_engine import (
    PedagogyEngine,
    PedagogyFastSignals,
    StudentState,
    StreamPedagogyMeta,
)


class FakeEmbeddingService:
    """Controllable embedding service for greeting/off-topic filter tests."""

    def __init__(self) -> None:
        self.greeting_result = False
        self.off_topic_result = False
        self.next_embedding = [0.1] * 256

    async def embed_text(self, text: str):
        return self.next_embedding

    def check_greeting(self, embedding):
        return self.greeting_result

    def check_off_topic(self, embedding):
        return self.off_topic_result


class FakeLLM:
    """Minimal LLM mock for two-step recovery metadata classification."""

    def __init__(self) -> None:
        self.last_usage = LLMUsage()
        self.call_kinds: list[str] = []
        self.responses: list[str] = [
            (
                '{"same_problem": false, "is_elaboration": false, '
                '"programming_difficulty": 3, "maths_difficulty": 3, "hint_level": 2}'
            )
        ]

    async def generate(self, system_prompt, messages, max_tokens=100):
        self.call_kinds.append("two_step_recovery_route")
        self.last_usage.input_tokens = 10
        self.last_usage.output_tokens = 5
        return self.responses.pop(0)

    def count_tokens(self, text):
        return max(1, len(text) // 4)


def _make_engine(embedding_service=None, llm=None):
    llm = llm or FakeLLM()
    return PedagogyEngine(embedding_service, llm)


def _make_state(prog=3.0, maths=3.0):
    return StudentState(
        user_id="test-user",
        effective_programming_level=prog,
        effective_maths_level=maths,
    )


@pytest.mark.asyncio
async def test_prepare_fast_signals_returns_greeting_canned_response() -> None:
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
async def test_prepare_fast_signals_fail_open_without_embedding_service() -> None:
    engine = _make_engine(embedding_service=None)
    state = _make_state()
    state.last_question_text = "Implement binary search"
    state.last_answer_text = "Start with low/high pointers."

    signals = await engine.prepare_fast_signals(
        "Can you explain step 2?",
        state,
        enable_greeting_filter=True,
        enable_off_topic_filter=True,
    )

    assert signals.filter_result is None
    assert signals.has_previous_exchange is True
    assert signals.previous_question_text == state.last_question_text
    assert signals.previous_answer_text == state.last_answer_text


def test_coerce_stream_meta_clamps_and_normalises() -> None:
    engine = _make_engine()
    state = _make_state()
    state.last_question_text = "Previous question"
    state.last_answer_text = "Previous answer"
    signals = PedagogyFastSignals(
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
    assert meta.source == "single_pass_header_route"


def test_coerce_stream_meta_forces_new_problem_without_previous_context() -> None:
    engine = _make_engine()
    state = _make_state()
    signals = PedagogyFastSignals(has_previous_exchange=False)

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


def test_build_emergency_full_hint_fallback_meta_uses_effective_levels() -> None:
    engine = _make_engine()
    state = _make_state(prog=4.4, maths=2.2)

    meta = engine.build_emergency_full_hint_fallback_meta(state, PedagogyFastSignals())

    assert meta.source == "emergency_full_hint_fallback"
    assert meta.same_problem is False
    assert meta.is_elaboration is False
    assert meta.hint_level == 5
    assert meta.programming_difficulty == 4
    assert meta.maths_difficulty == 2
    assert state.skip_next_ema_update_once is True


@pytest.mark.asyncio
async def test_classify_two_step_recovery_meta_returns_validated_metadata() -> None:
    llm = FakeLLM()
    llm.responses = [
        (
            '{"same_problem": true, "is_elaboration": true, '
            '"programming_difficulty": 4, "maths_difficulty": 2, "hint_level": 3}'
        )
    ]
    engine = _make_engine(llm=llm)
    state = _make_state()
    state.current_hint_level = 2
    state.current_programming_difficulty = 3
    state.current_maths_difficulty = 2
    state.last_question_text = "Implement binary search"
    state.last_answer_text = "Check the middle element."
    signals = await engine.prepare_fast_signals("Why does this work?", state)

    meta = await engine.classify_two_step_recovery_meta(
        "Why does this work?",
        student_state=state,
        fast_signals=signals,
    )

    assert meta.source == "two_step_recovery_route"
    assert meta.same_problem is True
    assert meta.is_elaboration is True
    assert meta.programming_difficulty == 4
    assert meta.maths_difficulty == 2
    assert meta.hint_level == 3
    assert state.skip_next_ema_update_once is False
    assert llm.call_kinds == ["two_step_recovery_route"]


@pytest.mark.asyncio
async def test_classify_two_step_recovery_meta_falls_back_to_emergency_meta() -> None:
    llm = FakeLLM()
    llm.responses = ['{"same_problem": true, "oops": 1}']
    engine = _make_engine(llm=llm)
    state = _make_state(prog=3.6, maths=2.4)
    state.current_hint_level = 2
    state.current_programming_difficulty = 4
    state.current_maths_difficulty = 3
    state.last_question_text = "Previous question"
    state.last_answer_text = "Previous answer"
    signals = await engine.prepare_fast_signals("Explain more", state)

    meta = await engine.classify_two_step_recovery_meta(
        "Explain more",
        student_state=state,
        fast_signals=signals,
    )

    assert meta.source == "emergency_full_hint_fallback"
    assert meta.same_problem is False
    assert meta.hint_level == 5
    assert meta.programming_difficulty == 4
    assert meta.maths_difficulty == 2
    assert state.skip_next_ema_update_once is True


def test_two_step_recovery_payload_truncates_current_message_for_latency() -> None:
    llm = FakeLLM()
    engine = _make_engine(llm=llm)
    state = _make_state()
    signals = PedagogyFastSignals()
    long_message = "token " * 2000

    payload = engine._build_two_step_recovery_payload(
        user_message=long_message,
        student_state=state,
        fast_signals=signals,
    )

    current_message = str(payload["current_message"])
    assert llm.count_tokens(current_message) <= 320
    assert current_message


def test_apply_stream_meta_skips_one_ema_update_after_emergency_fallback() -> None:
    engine = _make_engine()
    state = _make_state(prog=3.0, maths=3.0)
    state.last_question_text = "old"
    state.last_answer_text = "old answer"
    state.current_hint_level = 2
    state.current_programming_difficulty = 4
    state.current_maths_difficulty = 4
    state.skip_next_ema_update_once = True
    before_prog = state.effective_programming_level
    before_maths = state.effective_maths_level

    engine.apply_stream_meta(
        state,
        StreamPedagogyMeta(
            same_problem=False,
            is_elaboration=False,
            programming_difficulty=2,
            maths_difficulty=2,
            hint_level=1,
            source="emergency_full_hint_fallback",
        ),
    )

    assert state.skip_next_ema_update_once is False
    assert state.effective_programming_level == before_prog
    assert state.effective_maths_level == before_maths
    assert state.current_hint_level == 1


def test_update_previous_exchange_text_stores_text() -> None:
    engine = _make_engine()
    state = _make_state()

    engine.update_previous_exchange_text(
        state,
        question="What is recursion?",
        answer="A function can call itself.",
    )

    assert state.last_question_text == "What is recursion?"
    assert state.last_answer_text == "A function can call itself."


def test_ema_level_update() -> None:
    state = _make_state(prog=3.0, maths=3.0)
    state.current_programming_difficulty = 4
    state.current_maths_difficulty = 3
    state.current_hint_level = 2

    PedagogyEngine._update_effective_levels(state)

    assert abs(state.effective_programming_level - 3.04) < 0.01
