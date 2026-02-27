import logging

from app.ai.llm_base import LLMProvider
from app.ai.prompts import (
    BASE_SYSTEM_PROMPT,
    PROGRAMMING_HINT_INSTRUCTIONS,
    MATHS_HINT_INSTRUCTIONS,
    PROGRAMMING_LEVEL_INSTRUCTIONS,
    MATHS_LEVEL_INSTRUCTIONS,
    SINGLE_PASS_PEDAGOGY_PROTOCOL_PROMPT,
)

logger = logging.getLogger(__name__)

COMPRESSION_PROMPT = (
    "Summarise the following tutoring conversation in 2-3 sentences. "
    "Preserve: topics discussed, problems attempted, hint levels reached, "
    "and any key conclusions. Be concise."
)


def build_system_prompt(
    programming_hint_level: int,
    maths_hint_level: int,
    programming_level: int,
    maths_level: int,
    notebook_context: str | None = None,
) -> str:
    """Assemble the full system prompt from base + hint instructions + student levels."""
    parts = [
        BASE_SYSTEM_PROMPT,
        "",
        PROGRAMMING_HINT_INSTRUCTIONS.get(programming_hint_level, PROGRAMMING_HINT_INSTRUCTIONS[3]),
        "",
        MATHS_HINT_INSTRUCTIONS.get(maths_hint_level, MATHS_HINT_INSTRUCTIONS[3]),
        "",
        PROGRAMMING_LEVEL_INSTRUCTIONS.get(programming_level, PROGRAMMING_LEVEL_INSTRUCTIONS[3]),
        "",
        MATHS_LEVEL_INSTRUCTIONS.get(maths_level, MATHS_LEVEL_INSTRUCTIONS[3]),
    ]
    if notebook_context:
        parts.extend(["", notebook_context])
    return "\n".join(parts)


def build_single_pass_system_prompt(
    programming_level: int,
    maths_level: int,
    *,
    pedagogy_context: str,
    notebook_context: str | None = None,
) -> str:
    """Assemble the single-pass prompt that emits hidden metadata then the answer."""

    prog_hint_lines: list[str] = ["Programming hint level rules (choose the level computed by the formula):"]
    for level in sorted(PROGRAMMING_HINT_INSTRUCTIONS):
        prog_hint_lines.append(f"- Level {level}: {PROGRAMMING_HINT_INSTRUCTIONS[level]}")

    maths_hint_lines: list[str] = ["Maths hint level rules (choose the level computed by the formula):"]
    for level in sorted(MATHS_HINT_INSTRUCTIONS):
        maths_hint_lines.append(f"- Level {level}: {MATHS_HINT_INSTRUCTIONS[level]}")

    parts = [
        BASE_SYSTEM_PROMPT,
        "",
        SINGLE_PASS_PEDAGOGY_PROTOCOL_PROMPT,
        "",
        "\n".join(prog_hint_lines),
        "",
        "\n".join(maths_hint_lines),
        "",
        PROGRAMMING_LEVEL_INSTRUCTIONS.get(programming_level, PROGRAMMING_LEVEL_INSTRUCTIONS[3]),
        "",
        MATHS_LEVEL_INSTRUCTIONS.get(maths_level, MATHS_LEVEL_INSTRUCTIONS[3]),
        "",
        pedagogy_context,
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
    *,
    cached_summary: str | None = None,
    cached_summary_message_count: int | None = None,
    allow_inline_compression: bool = True,
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

    # Need compression or truncation.
    # Keep recent messages in ~50% of budget, then prefer a cached summary.
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

    cached_messages = _build_cached_summary_messages(
        chat_history=chat_history,
        llm=llm,
        budget=budget,
        current_msg=current_msg,
        cached_summary=cached_summary,
        cached_summary_message_count=cached_summary_message_count,
    )
    if cached_messages is not None:
        return cached_messages

    if allow_inline_compression and older:
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


def _build_cached_summary_messages(
    *,
    chat_history: list[dict],
    llm: LLMProvider,
    budget: int,
    current_msg: dict,
    cached_summary: str | None,
    cached_summary_message_count: int | None,
) -> list[dict] | None:
    """Build a context list from a hidden cached summary plus recent raw turns."""

    summary_text = (cached_summary or "").strip()
    if not summary_text:
        return None
    try:
        prefix_count = int(cached_summary_message_count or 0)
    except (TypeError, ValueError):
        return None
    if prefix_count <= 0 or prefix_count > len(chat_history):
        return None

    summary_msgs = [
        {
            "role": "user",
            "content": f"[Earlier conversation summary]\n{summary_text}",
        },
        {
            "role": "assistant",
            "content": "Understood, I have the context from our earlier discussion.",
        },
    ]

    summary_tokens = sum(llm.count_tokens(msg.get("content", "")) for msg in summary_msgs)
    if summary_tokens >= budget:
        return None

    tail = chat_history[prefix_count:]
    tail_selected = _select_recent_messages_by_budget(tail, llm, budget - summary_tokens)
    return summary_msgs + tail_selected + [current_msg]


def _select_recent_messages_by_budget(
    messages: list[dict],
    llm: LLMProvider,
    budget: int,
) -> list[dict]:
    """Return the most recent messages that fit within the given token budget."""

    if budget <= 0 or not messages:
        return []
    kept_reversed: list[dict] = []
    used = 0
    for msg in reversed(messages):
        tokens = llm.count_tokens(msg.get("content", ""))
        if used + tokens > budget:
            break
        kept_reversed.append(msg)
        used += tokens
    kept_reversed.reverse()
    return kept_reversed


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
