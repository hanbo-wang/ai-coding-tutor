"""LLM-based difficulty classification for student questions.

Sends a lightweight prompt to the configured LLM provider and parses
the response to obtain separate programming and maths difficulty
ratings on a 1-to-5 scale.
"""

import json
import logging
import re

from app.ai.llm_base import LLMProvider

logger = logging.getLogger(__name__)

CLASSIFY_PROMPT = (
    "You classify the difficulty of student questions for a coding tutor.\n"
    "\n"
    "Programming levels:\n"
    "1 - No experience. New to coding.\n"
    "2 - Understands variables, loops, and functions.\n"
    "3 - Can write multi-file programmes. Understands data structures.\n"
    "4 - Experienced with algorithms and design patterns.\n"
    "5 - Professional level. System design and optimisation.\n"
    "\n"
    "Mathematics levels:\n"
    "1 - Basic arithmetic only.\n"
    "2 - Comfortable with algebra and basic geometry.\n"
    "3 - Comfortable with calculus and linear algebra.\n"
    "4 - Comfortable with differential equations and proofs.\n"
    "5 - Research-level mathematics.\n"
    "\n"
    "Rate based on the knowledge required to understand and solve the question.\n"
    'Reply with ONLY a JSON object: {"programming": N, "maths": N}'
)


def _clamp(value: int) -> int:
    return max(1, min(5, value))


def _parse_response(text: str) -> tuple[int, int] | None:
    """Try to extract programming and maths difficulty from LLM output."""
    # Strategy 1: strict JSON parse
    try:
        data = json.loads(text.strip())
        return (
            _clamp(int(data["programming"])),
            _clamp(int(data["maths"])),
        )
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        pass

    # Strategy 2: regex fallback for numbers in JSON-like text
    prog_match = re.search(r'"programming"\s*:\s*(\d)', text)
    maths_match = re.search(r'"maths"\s*:\s*(\d)', text)
    if prog_match and maths_match:
        return (
            _clamp(int(prog_match.group(1))),
            _clamp(int(maths_match.group(1))),
        )

    return None


async def classify_difficulty(
    llm: LLMProvider,
    question: str,
    fallback_programming: int = 3,
    fallback_maths: int = 3,
    *,
    previous_question: str | None = None,
    previous_answer: str | None = None,
    same_problem_context: bool = False,
) -> tuple[int, int]:
    """Classify a question's programming and maths difficulty via the LLM.

    Returns (programming_difficulty, maths_difficulty), each in [1, 5].
    Falls back to the provided defaults on any failure.
    """
    user_payload = {
        "current_message": question,
    }
    if same_problem_context and previous_question and previous_answer:
        user_payload["previous_question"] = previous_question
        user_payload["previous_answer"] = previous_answer
        user_payload["instruction"] = (
            "Rate the difficulty of the SAME underlying problem being discussed. "
            "Use the previous tutoring exchange as context. "
            "Ignore the fact that the current message may be short or conversational."
        )
    else:
        user_payload["instruction"] = (
            "Rate the difficulty of the problem in the current message."
        )

    try:
        response = await llm.generate(
            system_prompt=CLASSIFY_PROMPT,
            messages=[{"role": "user", "content": json.dumps(user_payload)}],
            max_tokens=30,
        )
        result = _parse_response(response)
        if result:
            logger.info("Classified difficulty: prog=%d, maths=%d", *result)
            return result
        logger.warning("Could not parse difficulty from LLM: %r", response)
    except Exception as e:
        logger.warning("Difficulty classification failed: %s", e)

    return (fallback_programming, fallback_maths)
