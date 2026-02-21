"""Admin usage endpoint unit tests."""

from app.config import LLM_PRICING
from app.routers.admin import _estimate_cost


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
