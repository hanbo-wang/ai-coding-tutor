"""LLM-based same-problem and elaboration classification for tutoring chat."""

import json
import logging
import re

from app.ai.llm_base import LLMProvider

logger = logging.getLogger(__name__)

SAME_PROBLEM_PROMPT = (
    "You classify whether a student's new message is about the same tutoring problem "
    "as the previous tutoring exchange.\n"
    "\n"
    "Definitions:\n"
    "- same_problem=true: the student is continuing the same question/problem/task, "
    "including clarification, step-by-step requests, edge cases, debugging the same code, "
    "or asking for a different explanation of the same underlying problem.\n"
    "- same_problem=false: the student has started a new question/problem/task, even if it is "
    "in the same subject or programming language.\n"
    "- is_elaboration=true only when same_problem=true and the message is mainly a generic "
    "follow-up request with little new topic content (examples: 'I don't understand', "
    "'explain more', 'why?', 'show me step by step').\n"
    "- is_elaboration=false for substantive follow-ups that add topic-specific content.\n"
    "\n"
    "Be strict about 'same problem' meaning the same underlying task, not merely the same subject.\n"
    'Reply with ONLY a JSON object: {"same_problem": true|false, "is_elaboration": true|false}'
)


def _to_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalised = value.strip().lower()
        if normalised in {"true", "yes", "y", "1"}:
            return True
        if normalised in {"false", "no", "n", "0"}:
            return False
    return None


def _parse_response(text: str) -> tuple[bool, bool] | None:
    """Parse the LLM response into (same_problem, is_elaboration)."""
    try:
        data = json.loads(text.strip())
        same_problem = _to_bool(data.get("same_problem"))
        is_elaboration = _to_bool(data.get("is_elaboration"))
        if same_problem is None or is_elaboration is None:
            raise ValueError("Missing boolean fields")
        if not same_problem:
            is_elaboration = False
        return same_problem, is_elaboration
    except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
        pass

    same_problem_match = re.search(
        r'"same_problem"\s*:\s*(true|false|"true"|"false")',
        text,
        flags=re.IGNORECASE,
    )
    is_elaboration_match = re.search(
        r'"is_elaboration"\s*:\s*(true|false|"true"|"false")',
        text,
        flags=re.IGNORECASE,
    )
    if not same_problem_match or not is_elaboration_match:
        return None

    same_problem = _to_bool(same_problem_match.group(1).strip('"'))
    is_elaboration = _to_bool(is_elaboration_match.group(1).strip('"'))
    if same_problem is None or is_elaboration is None:
        return None
    if not same_problem:
        is_elaboration = False
    return same_problem, is_elaboration


def _build_user_payload(
    current_message: str,
    previous_question: str,
    previous_answer: str,
) -> str:
    payload = {
        "previous_question": previous_question,
        "previous_answer": previous_answer,
        "current_message": current_message,
    }
    return json.dumps(payload, ensure_ascii=True)


async def classify_same_problem(
    llm: LLMProvider,
    *,
    current_message: str,
    previous_question: str,
    previous_answer: str,
    fallback_same_problem: bool = False,
    fallback_is_elaboration: bool = False,
) -> tuple[bool, bool]:
    """Return (same_problem, is_elaboration) using the configured LLM."""
    if not previous_question.strip() or not previous_answer.strip():
        return (fallback_same_problem, fallback_is_elaboration)

    try:
        response = await llm.generate(
            system_prompt=SAME_PROBLEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": _build_user_payload(
                        current_message=current_message,
                        previous_question=previous_question,
                        previous_answer=previous_answer,
                    ),
                }
            ],
            max_tokens=60,
        )
        result = _parse_response(response)
        if result:
            logger.info(
                "Same-problem classification: same_problem=%s, is_elaboration=%s",
                result[0],
                result[1],
            )
            return result
        logger.warning("Could not parse same-problem classification from LLM: %r", response)
    except Exception as e:
        logger.warning("Same-problem classification failed: %s", e)

    if not fallback_same_problem:
        fallback_is_elaboration = False
    return (fallback_same_problem, fallback_is_elaboration)
