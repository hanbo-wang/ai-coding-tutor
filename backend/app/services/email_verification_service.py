"""Email verification code issuance and validation."""

from __future__ import annotations

import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.email_verification import EmailVerificationToken
from app.services.email_service import EmailDeliveryError, send_transactional_email

EmailVerificationPurpose = Literal["register", "reset_password"]

REGISTER_PURPOSE: EmailVerificationPurpose = "register"
RESET_PASSWORD_PURPOSE: EmailVerificationPurpose = "reset_password"


class VerificationCodeError(Exception):
    """Base error for verification code operations."""


@dataclass(slots=True)
class ResendCooldownError(VerificationCodeError):
    retry_after_seconds: int


def _now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _normalise_email(email: str) -> str:
    return email.strip().lower()


def _generate_code() -> str:
    return str(secrets.randbelow(1_000_000)).zfill(6)


def _hash_code(*, email: str, purpose: EmailVerificationPurpose, code: str) -> str:
    secret = settings.email_code_hmac_secret.strip() or settings.jwt_secret_key
    payload = f"{email}:{purpose}:{code}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, sha256).hexdigest()


def _build_email_content(
    purpose: EmailVerificationPurpose, code: str
) -> tuple[str, str]:
    ttl_minutes = max(1, settings.email_code_ttl_seconds // 60)
    if purpose == REGISTER_PURPOSE:
        subject = "Your registration verification code"
        intro = (
            "Use this code to finish creating your account. "
            "For your safety, do not share it with anyone."
        )
    else:
        subject = "Your password reset verification code"
        intro = (
            "Use this code to reset your password. "
            "If you did not request this, you can safely ignore this email."
        )

    html = _build_outlook_html_email(
        title=subject,
        intro=intro,
        code=code,
        ttl_minutes=ttl_minutes,
    )
    return subject, html


def _build_outlook_html_email(
    *, title: str, intro: str, code: str, ttl_minutes: int
) -> str:
    """Build a transactional HTML email that renders reliably in Outlook clients."""
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta name="x-apple-disable-message-reformatting" />
    <title>{title}</title>
  </head>
  <body style="margin:0;padding:0;background-color:#f5f7fb;">
    <!--[if mso]>
    <style type="text/css">
      body, table, td, p, a {{
        font-family: Arial, sans-serif !important;
      }}
    </style>
    <![endif]-->
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background-color:#f5f7fb;">
      <tr>
        <td align="center" style="padding:24px 12px;">
          <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="max-width:560px;background-color:#ffffff;border:1px solid #dfe3eb;border-radius:8px;">
            <tr>
              <td style="padding:24px 24px 8px 24px;font-family:Arial,sans-serif;font-size:24px;line-height:30px;font-weight:700;color:#1b1f2a;">
                {title}
              </td>
            </tr>
            <tr>
              <td style="padding:0 24px 16px 24px;font-family:Arial,sans-serif;font-size:16px;line-height:24px;color:#2f3947;">
                {intro}
              </td>
            </tr>
            <tr>
              <td align="center" style="padding:4px 24px 20px 24px;">
                <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="border:1px solid #d7dce5;border-radius:6px;background-color:#f8fafc;">
                  <tr>
                    <td style="padding:14px 22px;font-family:'Courier New',Courier,monospace;font-size:30px;line-height:32px;letter-spacing:6px;font-weight:700;color:#111827;text-align:center;">
                      {code}
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td style="padding:0 24px 20px 24px;font-family:Arial,sans-serif;font-size:14px;line-height:22px;color:#4b5563;">
                This code expires in {ttl_minutes} minutes.
              </td>
            </tr>
            <tr>
              <td style="padding:0 24px 24px 24px;font-family:Arial,sans-serif;font-size:13px;line-height:20px;color:#6b7280;">
                If this request was not made by you, no further action is required.
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""


async def issue_email_verification_code(
    db: AsyncSession,
    *,
    email: str,
    purpose: EmailVerificationPurpose,
) -> None:
    """Issue a new code and send it by email."""
    normalised_email = _normalise_email(email)
    now = _now_utc()

    result = await db.execute(
        select(EmailVerificationToken).where(
            EmailVerificationToken.email == normalised_email,
            EmailVerificationToken.purpose == purpose,
        )
    )
    token = result.scalar_one_or_none()

    if token and token.resend_available_at > now:
        remaining = int((token.resend_available_at - now).total_seconds())
        raise ResendCooldownError(retry_after_seconds=max(1, remaining))

    code = _generate_code()
    code_hash = _hash_code(email=normalised_email, purpose=purpose, code=code)
    expires_at = now + timedelta(seconds=settings.email_code_ttl_seconds)
    resend_available_at = now + timedelta(
        seconds=settings.email_code_resend_cooldown_seconds
    )

    if token is None:
        token = EmailVerificationToken(
            email=normalised_email,
            purpose=purpose,
            code_hash=code_hash,
            expires_at=expires_at,
            failed_attempts=0,
            resend_available_at=resend_available_at,
            consumed_at=None,
        )
        db.add(token)
    else:
        token.code_hash = code_hash
        token.expires_at = expires_at
        token.failed_attempts = 0
        token.resend_available_at = resend_available_at
        token.consumed_at = None

    await db.commit()

    subject, html_content = _build_email_content(purpose, code)
    try:
        await send_transactional_email(
            to_email=normalised_email,
            subject=subject,
            html_content=html_content,
        )
    except EmailDeliveryError:
        # Allow immediate re-send when delivery fails upstream.
        token.resend_available_at = now
        await db.commit()
        raise


async def verify_email_verification_code(
    db: AsyncSession,
    *,
    email: str,
    purpose: EmailVerificationPurpose,
    code: str,
) -> bool:
    """Validate and consume a code. Returns True when valid."""
    normalised_email = _normalise_email(email)
    now = _now_utc()

    result = await db.execute(
        select(EmailVerificationToken).where(
            EmailVerificationToken.email == normalised_email,
            EmailVerificationToken.purpose == purpose,
        )
    )
    token = result.scalar_one_or_none()
    if token is None:
        return False
    if token.consumed_at is not None:
        return False
    if token.expires_at <= now:
        return False
    if token.failed_attempts >= settings.email_code_max_attempts:
        return False

    expected_hash = _hash_code(email=normalised_email, purpose=purpose, code=code)
    if not hmac.compare_digest(expected_hash, token.code_hash):
        token.failed_attempts += 1
        if token.failed_attempts >= settings.email_code_max_attempts:
            token.consumed_at = now
        await db.commit()
        return False

    token.consumed_at = now
    await db.commit()
    return True
