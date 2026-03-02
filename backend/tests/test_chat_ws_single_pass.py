"""WebSocket chat integration tests for single-pass hidden metadata streaming."""

from __future__ import annotations

import asyncio
import json
import uuid
from types import SimpleNamespace

import app.models  # noqa: F401
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.ai.llm_base import LLMError, LLMProvider, LLMUsage
from app.ai.llm_factory import LLMTarget
from app.ai.pedagogy_engine import PedagogyFastSignals, ProcessResult, StreamPedagogyMeta
from app.models.chat import ChatMessage
from app.models.user import Base, User
from app.routers.chat import router as chat_router


def _run(coro):
    return asyncio.run(coro)


class _FakeStreamLLM(LLMProvider):
    """LLM stub that streams a predefined sequence of chunks."""

    def __init__(self, chunks: list[str] | list[list[str]]) -> None:
        super().__init__()
        if chunks and isinstance(chunks[0], list):  # type: ignore[index]
            self._calls = [list(call) for call in chunks]  # type: ignore[arg-type]
        else:
            self._calls = [list(chunks)]  # type: ignore[arg-type]
        self.call_count = 0
        self.system_prompts: list[str] = []
        # Keep these aligned with supported ids so factory-derived fallback logic
        # still treats the fake provider as a valid active target.
        self.provider_id = "openai"
        self.model_id = "gpt-5-mini"

    async def generate_stream(self, system_prompt, messages, max_tokens=2048):
        self.call_count += 1
        self.system_prompts.append(system_prompt)
        self.last_usage = LLMUsage(input_tokens=17, output_tokens=11)
        call_index = min(self.call_count - 1, len(self._calls) - 1)
        for chunk in self._calls[call_index]:
            yield chunk

    def count_tokens(self, text: str) -> int:
        return max(1, len(text.split()))


class _AlwaysUnavailableLLM(LLMProvider):
    """LLM stub that always fails with a transient unavailable error."""

    def __init__(self, *, provider_id: str, model_id: str) -> None:
        super().__init__()
        self.provider_id = provider_id
        self.model_id = model_id
        self.call_count = 0

    async def generate_stream(self, system_prompt, messages, max_tokens=2048):
        self.call_count += 1
        self.last_usage = LLMUsage(input_tokens=13, output_tokens=0)
        raise LLMError("upstream temporarily unavailable")
        yield  # pragma: no cover

    def count_tokens(self, text: str) -> int:
        return max(1, len(text.split()))


class _HeaderThenFailLLM(LLMProvider):
    """LLM stub that emits visible output and then fails."""

    def __init__(self, *, provider_id: str, model_id: str) -> None:
        super().__init__()
        self.provider_id = provider_id
        self.model_id = model_id
        self.call_count = 0

    async def generate_stream(self, system_prompt, messages, max_tokens=2048):
        self.call_count += 1
        self.last_usage = LLMUsage(input_tokens=21, output_tokens=5)
        yield "<<GC_META_V1>>"
        yield '{"same_problem":false,"is_elaboration":false,'
        yield '"programming_difficulty":3,"maths_difficulty":2}'
        yield "<<END_GC_META>>"
        yield "Partial"
        raise LLMError("upstream temporarily unavailable")

    def count_tokens(self, text: str) -> int:
        return max(1, len(text.split()))


class _PlainErrorLLM(LLMProvider):
    """LLM stub that raises a non-transient plain exception."""

    def __init__(self, *, provider_id: str, model_id: str, message: str) -> None:
        super().__init__()
        self.provider_id = provider_id
        self.model_id = model_id
        self.message = message
        self.call_count = 0

    async def generate_stream(self, system_prompt, messages, max_tokens=2048):
        self.call_count += 1
        self.last_usage = LLMUsage(input_tokens=9, output_tokens=0)
        raise RuntimeError(self.message)
        yield  # pragma: no cover

    def count_tokens(self, text: str) -> int:
        return max(1, len(text.split()))


class _FakePedagogyEngine:
    """Small pedagogy stub for router integration tests."""

    def __init__(self) -> None:
        self.two_step_recovery_calls = 0

    async def prepare_fast_signals(self, *args, **kwargs) -> PedagogyFastSignals:
        return PedagogyFastSignals()

    def coerce_stream_meta(
        self,
        raw_meta,
        *,
        student_state,
        fast_signals,
        source="single_pass_header_route",
    ):
        return StreamPedagogyMeta(
            same_problem=bool(raw_meta.get("same_problem")),
            is_elaboration=bool(raw_meta.get("is_elaboration")),
            programming_difficulty=int(raw_meta.get("programming_difficulty", 3)),
            maths_difficulty=int(raw_meta.get("maths_difficulty", 3)),
            programming_hint_level=2,
            maths_hint_level=2,
            source=source,
        )

    async def classify_two_step_recovery_meta(
        self, user_message, *, student_state, fast_signals
    ):
        self.two_step_recovery_calls += 1
        return StreamPedagogyMeta(
            same_problem=False,
            is_elaboration=False,
            programming_difficulty=3,
            maths_difficulty=2,
            programming_hint_level=2,
            maths_hint_level=2,
            source="two_step_recovery_route",
        )

    def apply_stream_meta(self, student_state, meta):
        student_state.current_programming_difficulty = meta.programming_difficulty
        student_state.current_maths_difficulty = meta.maths_difficulty
        student_state.current_programming_hint_level = meta.programming_hint_level
        student_state.current_maths_hint_level = meta.maths_hint_level
        return ProcessResult(
            programming_difficulty=meta.programming_difficulty,
            maths_difficulty=meta.maths_difficulty,
            programming_hint_level=meta.programming_hint_level,
            maths_hint_level=meta.maths_hint_level,
            is_same_problem=meta.same_problem,
        )

    def update_previous_exchange_text(self, *args, **kwargs) -> None:
        return None


class _SessionAwareFallbackPedagogyEngine(_FakePedagogyEngine):
    """Pedagogy stub that exposes previous-Q+A carry-over via fallback metadata."""

    async def classify_two_step_recovery_meta(
        self, user_message, *, student_state, fast_signals
    ):
        self.two_step_recovery_calls += 1
        has_previous_exchange = bool(
            (getattr(student_state, "last_question_text", "") or "").strip()
            and (getattr(student_state, "last_answer_text", "") or "").strip()
        )
        return StreamPedagogyMeta(
            same_problem=has_previous_exchange,
            is_elaboration=False,
            programming_difficulty=3,
            maths_difficulty=3,
            programming_hint_level=2,
            maths_hint_level=2,
            source="two_step_recovery_route",
        )

    def update_previous_exchange_text(self, student_state, question, answer, **kwargs) -> None:
        student_state.last_question_text = question
        student_state.last_answer_text = answer


async def _create_user(session_factory: async_sessionmaker[AsyncSession]) -> User:
    async with session_factory() as db:
        user = User(
            email="ws-test@example.com",
            username="ws_tester",
            password_hash="x",
            programming_level=3,
            maths_level=3,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


async def _list_messages(
    session_factory: async_sessionmaker[AsyncSession], session_id: str
) -> list[ChatMessage]:
    async with session_factory() as db:
        result = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == uuid.UUID(session_id))
            .order_by(ChatMessage.created_at.asc())
        )
        return list(result.scalars().all())


def _make_ws_app() -> FastAPI:
    app = FastAPI(title="ws-chat-test")
    app.include_router(chat_router)
    return app


def _setup_ws_test_env(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    chunks: list[str] | list[list[str]] | None = None,
    *,
    pedagogy: _FakePedagogyEngine | None = None,
    llm_override: LLMProvider | None = None,
):
    db_path = tmp_path / "ws_chat.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    _run(_create_tables(engine))
    user = _run(_create_user(session_factory))

    if llm_override is not None:
        llm = llm_override
    else:
        llm = _FakeStreamLLM(chunks or [])
    pedagogy = pedagogy or _FakePedagogyEngine()
    scheduled: list[str] = []

    async def _fake_authenticate_ws(token: str):
        return SimpleNamespace(
            id=user.id,
            username=user.username,
            programming_level=user.programming_level,
            maths_level=user.maths_level,
            effective_programming_level=user.effective_programming_level,
            effective_maths_level=user.effective_maths_level,
        )

    async def _fake_get_ai_services(incoming_llm):
        return pedagogy

    async def _fake_check_weekly_limit(*args, **kwargs):
        return True

    monkeypatch.setattr("app.routers.chat.AsyncSessionLocal", session_factory)
    monkeypatch.setattr("app.routers.chat._authenticate_ws", _fake_authenticate_ws)
    monkeypatch.setattr("app.routers.chat.get_llm_provider", lambda _settings: llm)
    monkeypatch.setattr(
        "app.routers.chat.build_llm_provider_for_target",
        lambda _settings, _target: llm,
    )
    monkeypatch.setattr("app.routers.chat.get_ai_services", _fake_get_ai_services)
    monkeypatch.setattr("app.routers.chat.estimate_llm_cost_usd", lambda *a, **k: 0.0)
    monkeypatch.setattr("app.routers.chat.chat_service.check_weekly_limit", _fake_check_weekly_limit)
    monkeypatch.setattr(
        "app.routers.chat.chat_summary_cache_service.schedule_refresh",
        lambda session_id: scheduled.append(str(session_id)),
    )
    monkeypatch.setattr("app.routers.chat.rate_limiter.check_user", lambda user_id: True)
    monkeypatch.setattr("app.routers.chat.rate_limiter.check_global", lambda: True)
    monkeypatch.setattr("app.routers.chat.rate_limiter.record", lambda user_id: None)
    monkeypatch.setattr("app.routers.chat.connection_tracker.can_connect", lambda user_id: True)
    monkeypatch.setattr("app.routers.chat.connection_tracker.add", lambda user_id, conn_id: None)
    monkeypatch.setattr("app.routers.chat.connection_tracker.remove", lambda user_id, conn_id: None)

    client = TestClient(_make_ws_app())
    return client, session_factory, engine, scheduled, llm, pedagogy


async def _create_tables(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _collect_until_done(ws) -> list[dict]:
    events: list[dict] = []
    while True:
        event = ws.receive_json()
        events.append(event)
        if event.get("type") == "done":
            break
    return events


def _collect_until_terminal(ws) -> list[dict]:
    events: list[dict] = []
    while True:
        event = ws.receive_json()
        events.append(event)
        if event.get("type") in {"done", "error"}:
            break
    return events


def test_ws_single_pass_emits_meta_before_token_and_strips_header(tmp_path, monkeypatch) -> None:
    """The router should hide metadata headers and emit `meta` before visible tokens."""

    chunks = [
        "<<GC_META_V1>>",
        '{"same_problem":false,"is_elaboration":false,',
        '"programming_difficulty":3,"maths_difficulty":2}',
        "<<END_GC_META>>",
        "Hello",
        " world",
    ]
    client, session_factory, engine, scheduled, _llm, _pedagogy = _setup_ws_test_env(
        tmp_path, monkeypatch, chunks
    )
    try:
        with client.websocket_connect("/ws/chat?token=test") as ws:
            ws.send_text(json.dumps({"content": "Explain binary search"}))
            events = _collect_until_done(ws)

        event_types = [e["type"] for e in events]
        assert "meta" in event_types
        assert "token" in event_types
        assert event_types.index("meta") < event_types.index("token")

        token_text = "".join(e["content"] for e in events if e["type"] == "token")
        assert token_text == "Hello world"
        assert "<<GC_META_V1>>" not in token_text
        assert "<<END_GC_META>>" not in token_text

        meta_event = next(e for e in events if e["type"] == "meta")
        done_event = next(e for e in events if e["type"] == "done")
        assert meta_event["source"] == "single_pass_header_route"
        assert done_event["programming_difficulty"] == meta_event["programming_difficulty"]
        assert done_event["maths_difficulty"] == meta_event["maths_difficulty"]
        assert done_event["programming_hint_level"] == meta_event["programming_hint_level"]
        assert done_event["maths_hint_level"] == meta_event["maths_hint_level"]

        session_event = next(e for e in events if e["type"] == "session")
        stored_messages = _run(_list_messages(session_factory, session_event["session_id"]))
        assert [m.role for m in stored_messages] == ["user", "assistant"]
        assert stored_messages[1].content == "Hello world"
        assert "<<GC_META_V1>>" not in stored_messages[1].content
        assert len(scheduled) == 1
    finally:
        client.close()
        _run(engine.dispose())


def test_ws_single_pass_missing_header_discards_output_and_regenerates(tmp_path, monkeypatch) -> None:
    """Missing headers should discard the failed body and regenerate via recovery route."""

    chunks = [["Hello", " ", "world"], ["Recovered", " ", "reply"]]
    client, session_factory, engine, scheduled, _llm, _pedagogy = _setup_ws_test_env(
        tmp_path, monkeypatch, chunks
    )
    try:
        with client.websocket_connect("/ws/chat?token=test") as ws:
            ws.send_text(json.dumps({"content": "Short reply"}))
            events = _collect_until_done(ws)

        event_types = [e["type"] for e in events]
        assert "meta" in event_types
        assert "token" in event_types
        assert event_types.index("meta") < event_types.index("token")

        meta_event = next(e for e in events if e["type"] == "meta")
        assert meta_event["source"] == "two_step_recovery_route"

        token_events = [e for e in events if e["type"] == "token"]
        assert [e["content"] for e in token_events] == ["Recovered", " ", "reply"]

        status_events = [e for e in events if e["type"] == "status"]
        assert [e["attempt"] for e in status_events] == [1, 2, 3]
        assert all(e["max_attempts"] == 3 for e in status_events)
        assert all(e["stage"] == "single_pass_header_meta" for e in status_events)

        session_event = next(e for e in events if e["type"] == "session")
        stored_messages = _run(_list_messages(session_factory, session_event["session_id"]))
        assert stored_messages[1].content == "Recovered reply"
        assert _llm.call_count == 5
        assert len(scheduled) == 1
    finally:
        client.close()
        _run(engine.dispose())


def test_ws_auto_mode_degrades_to_two_step_recovery_after_header_failures(
    tmp_path, monkeypatch
) -> None:
    """Auto mode should switch to the recovery route after repeated header parse failures."""

    monkeypatch.setattr("app.routers.chat.settings.chat_metadata_route_mode", "auto")
    monkeypatch.setattr(
        "app.routers.chat.settings.chat_single_pass_header_failures_before_two_step_recovery", 1
    )
    llm_calls = [
        ["No", " header"],  # First turn: failed single-pass attempt (discarded)
        ["Still", " no header"],  # First turn: single-pass parse retry 1 (discarded)
        ["Again", " no header"],  # First turn: single-pass parse retry 2 (discarded)
        ["Yet", " no header"],  # First turn: single-pass parse retry 3 (discarded)
        ["Recovered", " reply"],  # First turn: regenerated reply
        ["Second", " turn"],  # Second turn: recovery-route visible reply
    ]
    client, session_factory, engine, scheduled, llm, pedagogy = _setup_ws_test_env(
        tmp_path, monkeypatch, llm_calls
    )
    try:
        with client.websocket_connect("/ws/chat?token=test") as ws:
            ws.send_text(json.dumps({"content": "first"}))
            events1 = _collect_until_done(ws)
            session_id = next(e for e in events1 if e["type"] == "session")["session_id"]
            ws.send_text(json.dumps({"content": "second", "session_id": session_id}))
            events2 = _collect_until_done(ws)

        meta1 = next(e for e in events1 if e["type"] == "meta")
        meta2 = next(e for e in events2 if e["type"] == "meta")
        assert meta1["source"] == "two_step_recovery_route"
        assert meta2["source"] == "two_step_recovery_route"
        assert "".join(e["content"] for e in events1 if e["type"] == "token") == "Recovered reply"
        assert "".join(e["content"] for e in events2 if e["type"] == "token") == "Second turn"
        assert pedagogy.two_step_recovery_calls == 2
        assert llm.call_count == 6
        assert len(scheduled) == 2
    finally:
        client.close()
        _run(engine.dispose())


def test_ws_auto_mode_retries_single_pass_after_stable_two_step_recovery_turns(
    tmp_path, monkeypatch
) -> None:
    """Auto mode should retry the faster single-pass path after stable recovery turns."""

    monkeypatch.setattr("app.routers.chat.settings.chat_metadata_route_mode", "auto")
    monkeypatch.setattr(
        "app.routers.chat.settings.chat_single_pass_header_failures_before_two_step_recovery", 1
    )
    monkeypatch.setattr(
        "app.routers.chat.settings.chat_two_step_recovery_turns_before_single_pass_retry", 1
    )
    llm_calls = [
        ["No", " header"],  # First turn: failed single-pass attempt (discarded)
        ["Still", " no header"],  # First turn: single-pass parse retry 1 (discarded)
        ["Again", " no header"],  # First turn: single-pass parse retry 2 (discarded)
        ["Yet", " no header"],  # First turn: single-pass parse retry 3 (discarded)
        ["Recovered", " first"],  # First turn: regenerated reply, triggers degradation
        ["Two-step", " ok"],  # Second turn: recovery-route visible reply
        [  # Third turn: auto retries single-pass and receives a valid hidden header
            "<<GC_META_V1>>",
            '{"same_problem":false,"is_elaboration":false,'
            '"programming_difficulty":3,"maths_difficulty":2}',
            "<<END_GC_META>>",
            "Back",
            " again",
        ],
    ]
    client, session_factory, engine, scheduled, llm, pedagogy = _setup_ws_test_env(
        tmp_path, monkeypatch, llm_calls
    )
    try:
        with client.websocket_connect("/ws/chat?token=test") as ws:
            ws.send_text(json.dumps({"content": "first"}))
            events1 = _collect_until_done(ws)
            session_id = next(e for e in events1 if e["type"] == "session")["session_id"]
            ws.send_text(json.dumps({"content": "second", "session_id": session_id}))
            events2 = _collect_until_done(ws)
            ws.send_text(json.dumps({"content": "third", "session_id": session_id}))
            events3 = _collect_until_done(ws)

        meta1 = next(e for e in events1 if e["type"] == "meta")
        meta2 = next(e for e in events2 if e["type"] == "meta")
        meta3 = next(e for e in events3 if e["type"] == "meta")
        assert meta1["source"] == "two_step_recovery_route"
        assert meta2["source"] == "two_step_recovery_route"
        assert meta3["source"] == "single_pass_header_route"
        assert "".join(e["content"] for e in events3 if e["type"] == "token") == "Back again"
        assert pedagogy.two_step_recovery_calls == 2
        assert llm.call_count == 7
        assert len(scheduled) == 3
    finally:
        client.close()
        _run(engine.dispose())


def test_ws_auto_mode_does_not_retry_single_pass_after_emergency_recovery_meta(
    tmp_path, monkeypatch
) -> None:
    """Auto mode should only retry single-pass after successful recovery metadata turns."""

    monkeypatch.setattr("app.routers.chat.settings.chat_metadata_route_mode", "auto")
    monkeypatch.setattr(
        "app.routers.chat.settings.chat_single_pass_header_failures_before_two_step_recovery", 1
    )
    monkeypatch.setattr(
        "app.routers.chat.settings.chat_two_step_recovery_turns_before_single_pass_retry", 1
    )
    llm_calls = [
        ["No", " header"],  # First turn: failed single-pass attempt (discarded)
        ["Still", " no header"],  # First turn: single-pass parse retry 1 (discarded)
        ["Again", " no header"],  # First turn: single-pass parse retry 2 (discarded)
        ["Yet", " no header"],  # First turn: single-pass parse retry 3 (discarded)
        ["Recovered", " first"],  # First turn: regenerated reply, triggers degradation
        ["Emergency", " second"],  # Second turn: recovery-route visible reply
        ["Still", " recovery"],  # Third turn should remain recovery route
    ]
    client, session_factory, engine, scheduled, llm, pedagogy = _setup_ws_test_env(
        tmp_path, monkeypatch, llm_calls
    )

    async def _two_step_emergency_meta(user_message, *, student_state, fast_signals):
        pedagogy.two_step_recovery_calls += 1
        return StreamPedagogyMeta(
            same_problem=False,
            is_elaboration=False,
            programming_difficulty=3,
            maths_difficulty=3,
            programming_hint_level=5,
            maths_hint_level=5,
            source="emergency_full_hint_fallback",
        )

    pedagogy.classify_two_step_recovery_meta = _two_step_emergency_meta  # type: ignore[method-assign]

    try:
        with client.websocket_connect("/ws/chat?token=test") as ws:
            ws.send_text(json.dumps({"content": "first"}))
            events1 = _collect_until_done(ws)
            session_id = next(e for e in events1 if e["type"] == "session")["session_id"]
            ws.send_text(json.dumps({"content": "second", "session_id": session_id}))
            events2 = _collect_until_done(ws)
            ws.send_text(json.dumps({"content": "third", "session_id": session_id}))
            events3 = _collect_until_done(ws)

        meta1 = next(e for e in events1 if e["type"] == "meta")
        meta2 = next(e for e in events2 if e["type"] == "meta")
        meta3 = next(e for e in events3 if e["type"] == "meta")
        assert meta1["source"] == "emergency_full_hint_fallback"
        assert meta2["source"] == "emergency_full_hint_fallback"
        assert meta3["source"] == "emergency_full_hint_fallback"
        assert pedagogy.two_step_recovery_calls == 3
        assert llm.call_count == 7
        assert "".join(e["content"] for e in events3 if e["type"] == "token") == "Still recovery"
        assert len(scheduled) == 3
    finally:
        client.close()
        _run(engine.dispose())


def test_ws_hidden_pedagogy_state_is_isolated_between_new_sessions(
    tmp_path, monkeypatch
) -> None:
    """A new session on the same socket should not inherit previous-Q+A pedagogy state."""

    chunks = [["First reply"], ["Second reply"]]
    pedagogy = _SessionAwareFallbackPedagogyEngine()
    client, _session_factory, engine, scheduled, _llm, _pedagogy = _setup_ws_test_env(
        tmp_path,
        monkeypatch,
        chunks,
        pedagogy=pedagogy,
    )
    try:
        with client.websocket_connect("/ws/chat?token=test") as ws:
            ws.send_text(json.dumps({"content": "first"}))
            events1 = _collect_until_done(ws)
            ws.send_text(json.dumps({"content": "second"}))
            events2 = _collect_until_done(ws)

        session1 = next(e for e in events1 if e["type"] == "session")["session_id"]
        session2 = next(e for e in events2 if e["type"] == "session")["session_id"]
        meta1 = next(e for e in events1 if e["type"] == "meta")
        meta2 = next(e for e in events2 if e["type"] == "meta")

        assert session1 != session2
        assert meta1["source"] == "two_step_recovery_route"
        assert meta2["source"] == "two_step_recovery_route"
        assert meta1["same_problem"] is False
        assert meta2["same_problem"] is False
        assert len(scheduled) == 2
    finally:
        client.close()
        _run(engine.dispose())


def test_ws_auto_mode_header_failure_degrade_is_isolated_per_session(
    tmp_path, monkeypatch
) -> None:
    """Auto-mode degradation state should not leak from one session to another."""

    monkeypatch.setattr("app.routers.chat.settings.chat_metadata_route_mode", "auto")
    monkeypatch.setattr(
        "app.routers.chat.settings.chat_single_pass_header_failures_before_two_step_recovery", 1
    )
    llm_calls = [
        ["No", " header"],  # First session: initial single-pass fail
        ["Still", " no header"],  # First session: parse retry 1
        ["Again", " no header"],  # First session: parse retry 2
        ["Yet", " no header"],  # First session: parse retry 3
        ["Recovered", " first"],  # First session: two-step recovery visible reply
        [  # Second session: single-pass success remains isolated
            "<<GC_META_V1>>",
            '{"same_problem":false,"is_elaboration":false,'
            '"programming_difficulty":3,"maths_difficulty":2}',
            "<<END_GC_META>>",
            "Fresh",
            " session",
        ],
    ]
    client, _session_factory, engine, scheduled, llm, pedagogy = _setup_ws_test_env(
        tmp_path,
        monkeypatch,
        llm_calls,
    )
    try:
        with client.websocket_connect("/ws/chat?token=test") as ws:
            ws.send_text(json.dumps({"content": "first"}))
            events1 = _collect_until_done(ws)
            ws.send_text(json.dumps({"content": "second"}))
            events2 = _collect_until_done(ws)

        meta1 = next(e for e in events1 if e["type"] == "meta")
        meta2 = next(e for e in events2 if e["type"] == "meta")
        session1 = next(e for e in events1 if e["type"] == "session")["session_id"]
        session2 = next(e for e in events2 if e["type"] == "session")["session_id"]

        assert session1 != session2
        assert meta1["source"] == "two_step_recovery_route"
        assert meta2["source"] == "single_pass_header_route"
        assert "".join(e["content"] for e in events2 if e["type"] == "token") == "Fresh session"
        assert pedagogy.two_step_recovery_calls == 1
        assert llm.call_count == 6
        assert len(scheduled) == 2
    finally:
        client.close()
        _run(engine.dispose())


def test_ws_temporarily_unavailable_retries_same_model_then_switches_candidate(
    tmp_path, monkeypatch
) -> None:
    """Transient unavailable errors should retry five times before model switching."""

    primary_llm = _AlwaysUnavailableLLM(provider_id="openai", model_id="gpt-5-mini")
    fallback_llm = _FakeStreamLLM(
        [
            "<<GC_META_V1>>",
            '{"same_problem":false,"is_elaboration":false,',
            '"programming_difficulty":3,"maths_difficulty":2}',
            "<<END_GC_META>>",
            "Recovered",
            " response",
        ]
    )
    client, _session_factory, engine, _scheduled, _llm, _pedagogy = _setup_ws_test_env(
        tmp_path,
        monkeypatch,
        llm_override=primary_llm,
    )
    monkeypatch.setattr(
        "app.routers.chat.list_llm_fallback_targets",
        lambda *_args, **_kwargs: [
            LLMTarget(provider="anthropic", model_id="claude-3-5-haiku-latest")
        ],
    )

    def _build_target(_settings, target):
        if target.provider == "anthropic":
            return fallback_llm
        return primary_llm

    monkeypatch.setattr("app.routers.chat.build_llm_provider_for_target", _build_target)

    try:
        with client.websocket_connect("/ws/chat?token=test") as ws:
            ws.send_text(json.dumps({"content": "hello"}))
            events = _collect_until_done(ws)

        status_events = [e for e in events if e["type"] == "status"]
        same_model_attempts = [
            e["attempt"]
            for e in status_events
            if e["stage"] == "single_pass_header_route" and not e["switched_model"]
        ]
        switched_events = [
            e
            for e in status_events
            if e["stage"] == "single_pass_header_route" and e["switched_model"]
        ]
        assert same_model_attempts == [1, 2, 3, 4, 5]
        assert all(e["max_attempts"] == 5 for e in status_events)
        assert len(switched_events) == 1
        assert switched_events[0]["attempt"] == 5
        assert "".join(e["content"] for e in events if e["type"] == "token") == "Recovered response"
        assert primary_llm.call_count == 6
        assert fallback_llm.call_count == 1
    finally:
        client.close()
        _run(engine.dispose())


def test_ws_partial_visible_output_failure_does_not_retry_or_switch(
    tmp_path, monkeypatch
) -> None:
    """Failures after visible tokens should stop immediately with a standard error."""

    primary_llm = _HeaderThenFailLLM(provider_id="openai", model_id="gpt-5-mini")
    fallback_llm = _FakeStreamLLM(
        [
            "<<GC_META_V1>>",
            '{"same_problem":false,"is_elaboration":false,',
            '"programming_difficulty":3,"maths_difficulty":2}',
            "<<END_GC_META>>",
            "Should",
            " not-run",
        ]
    )
    client, _session_factory, engine, _scheduled, _llm, _pedagogy = _setup_ws_test_env(
        tmp_path,
        monkeypatch,
        llm_override=primary_llm,
    )
    monkeypatch.setattr(
        "app.routers.chat.list_llm_fallback_targets",
        lambda *_args, **_kwargs: [
            LLMTarget(provider="anthropic", model_id="claude-3-5-haiku-latest")
        ],
    )

    def _build_target(_settings, target):
        if target.provider == "anthropic":
            return fallback_llm
        return primary_llm

    monkeypatch.setattr("app.routers.chat.build_llm_provider_for_target", _build_target)

    try:
        with client.websocket_connect("/ws/chat?token=test") as ws:
            ws.send_text(json.dumps({"content": "hello"}))
            events = _collect_until_terminal(ws)

        assert any(e["type"] == "meta" for e in events)
        assert "".join(e["content"] for e in events if e["type"] == "token") == "Partial"
        error_event = next(e for e in events if e["type"] == "error")
        assert error_event["message"] == "AI service temporarily unavailable. Please try again."
        assert not any(e["type"] == "status" for e in events)
        assert primary_llm.call_count == 1
        assert fallback_llm.call_count == 0
        assert not any(e["type"] == "done" for e in events)
    finally:
        client.close()
        _run(engine.dispose())


def test_ws_non_unavailable_error_does_not_trigger_auto_retry(tmp_path, monkeypatch) -> None:
    """Non-unavailable errors should keep previous no-retry behaviour."""

    primary_llm = _PlainErrorLLM(
        provider_id="openai",
        model_id="gpt-5-mini",
        message="malformed prompt payload",
    )
    client, _session_factory, engine, _scheduled, _llm, _pedagogy = _setup_ws_test_env(
        tmp_path,
        monkeypatch,
        llm_override=primary_llm,
    )
    monkeypatch.setattr(
        "app.routers.chat.list_llm_fallback_targets",
        lambda *_args, **_kwargs: [
            LLMTarget(provider="anthropic", model_id="claude-3-5-haiku-latest")
        ],
    )
    monkeypatch.setattr(
        "app.routers.chat.build_llm_provider_for_target",
        lambda _settings, _target: primary_llm,
    )

    try:
        with client.websocket_connect("/ws/chat?token=test") as ws:
            ws.send_text(json.dumps({"content": "hello"}))
            events = _collect_until_terminal(ws)

        error_event = next(e for e in events if e["type"] == "error")
        assert error_event["message"] == "malformed prompt payload"
        assert not any(e["type"] == "status" for e in events)
        assert primary_llm.call_count == 1
    finally:
        client.close()
        _run(engine.dispose())
