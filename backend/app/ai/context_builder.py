import logging

from app.ai.llm_base import LLMProvider
from app.ai.prompts import (
    BASE_SYSTEM_PROMPT,
    HINT_LEVEL_INSTRUCTIONS,
    PROGRAMMING_LEVEL_INSTRUCTIONS,
    MATHS_LEVEL_INSTRUCTIONS,
)

logger = logging.getLogger(__name__)

COMPRESSION_PROMPT = (
    "Summarise the following tutoring conversation in 2-3 sentences. "
    "Preserve: topics discussed, problems attempted, hint levels reached, "
    "and any key conclusions. Be concise."
)


def build_system_prompt(
    hint_level: int,
    programming_level: int,
    maths_level: int,
    notebook_context: str | None = None,
) -> str:
    """Assemble the full system prompt from base + hint + student levels."""
    parts = [
        BASE_SYSTEM_PROMPT,
        "",
        HINT_LEVEL_INSTRUCTIONS.get(hint_level, HINT_LEVEL_INSTRUCTIONS[3]),
        "",
        PROGRAMMING_LEVEL_INSTRUCTIONS.get(programming_level, PROGRAMMING_LEVEL_INSTRUCTIONS[3]),
        "",
        MATHS_LEVEL_INSTRUCTIONS.get(maths_level, MATHS_LEVEL_INSTRUCTIONS[3]),
    ]
    if notebook_context:
        parts.extend(["", notebook_context])
    return "\n".join(parts)


async def build_context_messages(
    chat_history: list[dict],
    user_message: str,
    llm: LLMProvider,
    max_context_tokens: int,
    compression_threshold: float = 0.8,
) -> list[dict]:
    """Build a token-aware message list with automatic compression.

    If the full history fits within the threshold, include everything.
    If it exceeds the threshold, compress older messages into a summary
    and keep recent messages intact. Falls back to simple truncation
    if compression fails.
    """
    current_msg = {"role": "user", "content": user_message}
    current_tokens = llm.count_tokens(user_message)
    budget = max_context_tokens - current_tokens
    if budget <= 0:
        return [current_msg]

    if not chat_history:
        return [current_msg]

    # Calculate total history tokens
    msg_tokens = []
    total_history_tokens = 0
    for msg in chat_history:
        t = llm.count_tokens(msg.get("content", ""))
        msg_tokens.append(t)
        total_history_tokens += t

    threshold = int(max_context_tokens * compression_threshold)

    # If everything fits comfortably, use all messages
    if total_history_tokens + current_tokens <= threshold:
        return chat_history + [current_msg]

    # Need compression or truncation
    # Keep recent messages in ~50% of budget, compress the rest
    recent_budget = budget // 2
    recent: list[dict] = []
    recent_tokens = 0

    for i in range(len(chat_history) - 1, -1, -1):
        if recent_tokens + msg_tokens[i] > recent_budget:
            break
        recent.append(chat_history[i])
        recent_tokens += msg_tokens[i]

    recent.reverse()
    older_count = len(chat_history) - len(recent)
    older = chat_history[:older_count]

    if older:
        try:
            summary = await _compress_messages(older, llm)
            summary_msg = {
                "role": "user",
                "content": f"[Earlier conversation summary]\n{summary}",
            }
            summary_reply = {
                "role": "assistant",
                "content": "Understood, I have the context from our earlier discussion.",
            }
            return [summary_msg, summary_reply] + recent + [current_msg]
        except Exception as e:
            logger.warning("Context compression failed, using truncation: %s", e)

    # Fallback: simple truncation (just recent messages)
    return recent + [current_msg] if recent else [current_msg]


async def _compress_messages(
    messages: list[dict], llm: LLMProvider
) -> str:
    """Use the LLM to compress older messages into a brief summary."""
    conversation = "\n".join(
        f"{m['role'].upper()}: {m['content']}" for m in messages
    )

    summary_parts: list[str] = []
    async for chunk in llm.generate_stream(
        system_prompt=COMPRESSION_PROMPT,
        messages=[{"role": "user", "content": conversation}],
        max_tokens=300,
    ):
        summary_parts.append(chunk)
    return "".join(summary_parts)
