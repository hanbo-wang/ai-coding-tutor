import pytest

from app.config import _normalise_website_domain, _parse_admin_email_set


def test_parse_admin_email_set_supports_comma_and_space() -> None:
    parsed = _parse_admin_email_set(
        "Alice@example.com, bob@example.com  carol@example.com"
    )
    assert parsed == {
        "alice@example.com",
        "bob@example.com",
        "carol@example.com",
    }


def test_parse_admin_email_set_supports_json_list() -> None:
    parsed = _parse_admin_email_set('["Alice@example.com", "bob@example.com"]')
    assert parsed == {"alice@example.com", "bob@example.com"}


def test_normalise_website_domain_strips_scheme_and_trailing_slash() -> None:
    assert _normalise_website_domain(" https://example.com/ ") == "example.com"


def test_normalise_website_domain_rejects_empty_value() -> None:
    with pytest.raises(ValueError, match="WEBSITE_DOMAIN must not be empty"):
        _normalise_website_domain("   ")
