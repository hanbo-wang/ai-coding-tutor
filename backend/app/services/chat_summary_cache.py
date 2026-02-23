"""Hidden rolling summary cache for chat sessions."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.ai.context_builder import _compress_messages
from app.ai.llm_factory import get_llm_provider
from app.config import settings
from app.db.session import AsyncSessionLocal
from app.models.chat import ChatSession
from app.services import chat_service

logger = logging.getLogger(__name__)


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ChatSummaryCacheService:
    """Refresh rolling chat summaries without blocking the response path."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._dirty: dict[str, bool] = {}
        self._semaphore = asyncio.Semaphore(2)
        self.raw_tail_messages = 8
        self.min_summary_prefix_messages = 4

    def schedule_refresh(self, session_id: uuid.UUID) -> None:
        key = str(session_id)
        self._dirty[key] = True
        task = self._tasks.get(key)
        if task is None or task.done():
            self._tasks[key] = asyncio.create_task(
                self._run_refresh_loop(session_id),
                name=f"chat-summary-refresh-{key}",
            )

    async def _run_refresh_loop(self, session_id: uuid.UUID) -> None:
        key = str(session_id)
        lock = self._locks.setdefault(key, asyncio.Lock())
        try:
            while True:
                self._dirty[key] = False
                async with lock:
                    async with self._semaphore:
                        await self._refresh_once(session_id)
                if not self._dirty.get(key, False):
                    break
        except Exception as exc:  # pragma: no cover - defensive logging.
            logger.error("Summary cache refresh task failed for session %s: %s", key, exc)
        finally:
            self._tasks.pop(key, None)
            self._dirty.pop(key, None)

    async def _refresh_once(self, session_id: uuid.UUID) -> None:
        async with AsyncSessionLocal() as db:
            session = await db.get(ChatSession, session_id)
            if session is None:
                return

            chat_history = await chat_service.get_chat_history(db, session_id)
            if len(chat_history) <= self.raw_tail_messages + self.min_summary_prefix_messages:
                self._clear_cache(session)
                await db.commit()
                return

            prefix_count = max(0, len(chat_history) - self.raw_tail_messages)
            older = chat_history[:prefix_count]
            if len(older) < self.min_summary_prefix_messages:
                self._clear_cache(session)
                await db.commit()
                return

            llm = get_llm_provider(settings)
            try:
                summary = (await _compress_messages(older, llm)).strip()
            finally:
                close = getattr(llm, "close", None)
                if callable(close):
                    maybe_awaitable = close()
                    if asyncio.iscoroutine(maybe_awaitable):
                        await maybe_awaitable

            if not summary:
                self._clear_cache(session)
            else:
                session.context_summary_text = summary
                session.context_summary_message_count = prefix_count
                session.context_summary_updated_at = _utc_now_naive()
            await db.commit()
            logger.debug(
                "Refreshed chat summary cache for session %s (prefix_count=%d)",
                session_id,
                prefix_count,
            )

    @staticmethod
    def _clear_cache(session: ChatSession) -> None:
        session.context_summary_text = None
        session.context_summary_message_count = None
        session.context_summary_updated_at = None


chat_summary_cache_service = ChatSummaryCacheService()
