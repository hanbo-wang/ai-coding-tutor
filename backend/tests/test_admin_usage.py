"""Admin usage unit tests."""

from datetime import date

import pytest
from fastapi import HTTPException

from app.ai.pricing import estimate_llm_cost_usd
from app.routers.admin import (
    _aggregate_usage,
    _aggregate_usage_for_model,
    _estimate_cost,
    get_llm_errors,
    resolve_llm_error,
)


class _FakeAggregateResult:
    def __init__(self, row: tuple[int, int]) -> None:
        self._row = row

    def one(self) -> tuple[int, int]:
        return self._row


class _FakeAsyncSession:
    def __init__(self, rows: list[tuple]) -> None:
        self.rows = rows
        self.executed = []

    async def execute(self, statement):
        self.executed.append(statement)
        row = self.rows.pop(0)
        return _FakeAggregateResult(row)


def test_cost_calculation(monkeypatch) -> None:
    """Token counts should use the active provider/model pricing estimate."""
    monkeypatch.setattr("app.routers.admin.settings.llm_provider", "anthropic")
    monkeypatch.setattr("app.routers.admin.settings.llm_model_anthropic", "claude-sonnet-4-6")

    input_tokens = 1_000_000
    output_tokens = 1_000_000
    expected = estimate_llm_cost_usd(
        "anthropic",
        "claude-sonnet-4-6",
        input_tokens,
        output_tokens,
    )

    cost = _estimate_cost(input_tokens, output_tokens)
    assert cost == expected


def test_cost_zero_tokens(monkeypatch) -> None:
    """Zero tokens should produce zero cost."""
    monkeypatch.setattr("app.routers.admin.settings.llm_provider", "anthropic")
    cost = _estimate_cost(0, 0)
    assert cost == 0.0


@pytest.mark.asyncio
async def test_aggregate_usage_returns_totals_and_cost(monkeypatch) -> None:
    """Usage aggregation should include summed tokens and estimated cost."""
    monkeypatch.setattr("app.routers.admin.settings.llm_provider", "anthropic")
    db = _FakeAsyncSession([
        (1234, 5678),        # daily_token_usage totals
        (0.1234, 10, 8),     # cost sum, assistant count, cost count
    ])

    usage = await _aggregate_usage(db, start_date=date(2026, 1, 1))

    assert len(db.executed) == 2
    assert usage["input_tokens"] == 1234
    assert usage["output_tokens"] == 5678
    assert usage["estimated_cost_usd"] == 0.1234
    assert usage["estimated_cost_coverage"] == 0.8


@pytest.mark.asyncio
async def test_aggregate_usage_for_model_filters_and_returns_cost() -> None:
    """Model-scoped aggregation should return token totals, cost, and coverage."""
    db = _FakeAsyncSession([
        (321, 654, 0.4321, 12, 9),
    ])

    usage = await _aggregate_usage_for_model(
        db,
        start_date=date(2026, 1, 1),
        selected_provider_id="openai",
        canonical_provider_id="openai",
        model_id="gpt-5-mini",
    )

    assert len(db.executed) == 1
    assert usage["input_tokens"] == 321
    assert usage["output_tokens"] == 654
    assert usage["estimated_cost_usd"] == 0.4321
    assert usage["estimated_cost_coverage"] == 0.75


@pytest.mark.asyncio
async def test_get_llm_errors_passes_include_resolved_flag(monkeypatch) -> None:
    captured = {"include_resolved": None}

    def _fake_get_recent_llm_errors(*, include_resolved: bool = False):
        captured["include_resolved"] = include_resolved
        return [{"id": "err-1"}]

    monkeypatch.setattr(
        "app.routers.chat.get_recent_llm_errors",
        _fake_get_recent_llm_errors,
    )

    payload = await get_llm_errors(_=None, include_resolved=True)
    assert captured["include_resolved"] is True
    assert payload == {"errors": [{"id": "err-1"}]}


@pytest.mark.asyncio
async def test_resolve_llm_error_returns_success_when_found(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.routers.chat.mark_llm_error_resolved",
        lambda _error_id: True,
    )

    payload = await resolve_llm_error(error_id="err-1", _=None)
    assert payload["id"] == "err-1"
    assert payload["message"] == "LLM error alert resolved."


@pytest.mark.asyncio
async def test_resolve_llm_error_returns_404_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.routers.chat.mark_llm_error_resolved",
        lambda _error_id: False,
    )

    with pytest.raises(HTTPException) as exc_info:
        await resolve_llm_error(error_id="missing", _=None)

    assert getattr(exc_info.value, "status_code", None) == 404
