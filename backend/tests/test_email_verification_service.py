from app.services.email_verification_service import (
    REGISTER_PURPOSE,
    RESET_PASSWORD_PURPOSE,
    _build_email_content,
)


def test_registration_email_template_contains_html_root_tag() -> None:
    subject, html = _build_email_content(REGISTER_PURPOSE, "123456")
    assert "registration verification code" in subject.lower()
    assert "<html" in html.lower()
    assert "</html>" in html.lower()


def test_password_reset_email_template_contains_html_root_tag() -> None:
    subject, html = _build_email_content(RESET_PASSWORD_PURPOSE, "123456")
    assert "password reset verification code" in subject.lower()
    assert "<html" in html.lower()
    assert "</html>" in html.lower()
