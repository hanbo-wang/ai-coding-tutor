"""Tests for LLM-based same-problem classification helpers."""

import pytest

from app.ai.same_problem_classifier import _parse_response, classify_same_problem


def test_parse_response_strict_json() -> None:
    assert _parse_response('{"same_problem": true, "is_elaboration": false}') == (
        True,
        False,
    )


def test_parse_response_forces_elaboration_false_when_new_problem() -> None:
    assert _parse_response('{"same_problem": false, "is_elaboration": true}') == (
        False,
        False,
    )


def test_parse_response_regex_fallback() -> None:
    text = 'result: {"same_problem": "true", "is_elaboration": "true"}'
    assert _parse_response(text) == (True, True)


class _FakeLLM:
    def __init__(self, payload: str):
        self.payload = payload

    async def generate(self, system_prompt, messages, max_tokens=60):  # noqa: ANN001
        return self.payload


@pytest.mark.asyncio
async def test_classify_same_problem_returns_fallback_on_bad_payload() -> None:
    llm = _FakeLLM("not json")
    result = await classify_same_problem(
        llm,  # type: ignore[arg-type]
        current_message="Explain more",
        previous_question="What is recursion?",
        previous_answer="A function can call itself.",
        fallback_same_problem=True,
        fallback_is_elaboration=True,
    )
    assert result == (True, True)


@pytest.mark.asyncio
async def test_classify_same_problem_ignores_missing_context() -> None:
    llm = _FakeLLM('{"same_problem": true, "is_elaboration": true}')
    result = await classify_same_problem(
        llm,  # type: ignore[arg-type]
        current_message="Explain more",
        previous_question="",
        previous_answer="",
        fallback_same_problem=False,
        fallback_is_elaboration=False,
    )
    assert result == (False, False)
