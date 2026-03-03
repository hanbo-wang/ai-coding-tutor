"""Shared sanitisation helpers for chat messages before provider calls."""

from __future__ import annotations

from typing import Iterable

from app.ai.llm_base import LLMMessage


def normalise_text(value: object) -> str:
    """Return a safe text value for outbound model payloads."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def is_blank_text(value: str) -> bool:
    """Return True when a text value only contains whitespace."""
    return not value.strip()


def sanitise_history_messages(messages: Iterable[dict]) -> list[dict[str, str]]:
    """Keep only valid user/assistant text messages with non-empty content."""
    cleaned: list[dict[str, str]] = []
    for message in messages:
        role = str(message.get("role", "")).strip().lower()
        if role not in {"user", "assistant"}:
            continue
        content = normalise_text(message.get("content", ""))
        if is_blank_text(content):
            continue
        cleaned.append({"role": role, "content": content})
    return cleaned


def has_non_empty_messages(messages: Iterable[LLMMessage]) -> bool:
    """Return whether at least one message still has meaningful content."""
    for message in messages:
        content = message.get("content", "")
        if isinstance(content, str) and not is_blank_text(content):
            return True
        if isinstance(content, list):
            for part in content:
                part_type = str(part.get("type", "")).strip().lower()
                if part_type == "text" and not is_blank_text(
                    normalise_text(part.get("text", ""))
                ):
                    return True
                if part_type == "image" and normalise_text(part.get("data", "")).strip():
                    return True
    return False
