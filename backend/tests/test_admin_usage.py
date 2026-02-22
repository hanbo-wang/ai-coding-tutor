"""Admin usage unit tests."""

from datetime import date

import pytest

from app.config import LLM_PRICING
from app.routers.admin import _aggregate_usage, _estimate_cost


class _FakeAggregateResult:
    def __init__(self, row: tuple[int, int]) -> None:
        self._row = row

    def one(self) -> tuple[int, int]:
        return self._row


class _FakeAsyncSession:
    def __init__(self, row: tuple[int, int]) -> None:
        self.row = row
        self.executed = []

    async def execute(self, statement):
        self.executed.append(statement)
        return _FakeAggregateResult(self.row)


def test_cost_calculation(monkeypatch) -> None:
    """Token counts should produce correct estimated cost based on provider pricing."""
    monkeypatch.setattr("app.routers.admin.settings.llm_provider", "anthropic")
    pricing = LLM_PRICING["anthropic"]

    input_tokens = 1_000_000
    output_tokens = 1_000_000
    expected = pricing["input_per_mtok"] + pricing["output_per_mtok"]

    cost = _estimate_cost(input_tokens, output_tokens)
    assert abs(cost - expected) < 0.01


def test_cost_zero_tokens(monkeypatch) -> None:
    """Zero tokens should produce zero cost."""
    monkeypatch.setattr("app.routers.admin.settings.llm_provider", "anthropic")
    cost = _estimate_cost(0, 0)
    assert cost == 0.0


@pytest.mark.asyncio
async def test_aggregate_usage_returns_totals_and_cost(monkeypatch) -> None:
    """Usage aggregation should include summed tokens and estimated cost."""
    monkeypatch.setattr("app.routers.admin.settings.llm_provider", "anthropic")
    db = _FakeAsyncSession((1234, 5678))

    usage = await _aggregate_usage(db, start_date=date(2026, 1, 1))

    assert len(db.executed) == 1
    assert usage["input_tokens"] == 1234
    assert usage["output_tokens"] == 5678
    assert usage["estimated_cost_usd"] == _estimate_cost(1234, 5678)
