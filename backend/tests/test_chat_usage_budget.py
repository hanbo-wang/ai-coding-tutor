"""Tests for weekly token budget helper calculations."""

from datetime import date

from app.services.chat_service import calculate_weighted_token_usage, get_week_bounds


def test_calculate_weighted_token_usage_uses_input_divided_by_six() -> None:
    weighted = calculate_weighted_token_usage(600, 900)
    assert weighted == 1000.0


def test_get_week_bounds_returns_monday_to_sunday() -> None:
    week_start, week_end = get_week_bounds(date(2026, 2, 25))  # Wednesday
    assert week_start == date(2026, 2, 23)  # Monday
    assert week_end == date(2026, 3, 1)     # Sunday
