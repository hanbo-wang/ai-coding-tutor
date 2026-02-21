from app.config import _parse_admin_email_set


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
