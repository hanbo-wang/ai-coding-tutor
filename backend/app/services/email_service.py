"""Transactional email delivery helpers."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger("app.services.email_service")


class EmailDeliveryError(Exception):
    """Raised when an email cannot be delivered."""


def _build_brevo_url() -> str:
    base_url = settings.brevo_api_base_url.rstrip("/")
    return f"{base_url}/smtp/email"


def _extract_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            detail = payload.get("message") or payload.get("detail")
            if isinstance(detail, str) and detail.strip():
                return detail.strip()
    except ValueError:
        pass
    text = response.text.strip()
    if text:
        return text
    return f"HTTP {response.status_code}"


async def send_transactional_email(
    *,
    to_email: str,
    subject: str,
    html_content: str,
) -> str:
    """Send a transactional email through the configured provider."""
    if settings.email_provider == "noop":
        logger.info("Email provider is noop; skipped sending to %s", to_email)
        return "noop-message-id"

    if settings.email_provider != "brevo":
        raise EmailDeliveryError(f"Unsupported email provider: {settings.email_provider}")

    if not settings.brevo_api_key.strip():
        raise EmailDeliveryError("BREVO_API_KEY is missing.")
    if not settings.brevo_sender_email.strip():
        raise EmailDeliveryError("BREVO_SENDER_EMAIL is missing.")
    if "<html" not in html_content.lower():
        raise EmailDeliveryError("HTML email content must include an <html> tag.")

    payload: dict[str, Any] = {
        "sender": {
            "email": settings.brevo_sender_email.strip(),
            "name": settings.brevo_sender_name.strip() or "AI Coding Tutor",
        },
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html_content,
    }
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "api-key": settings.brevo_api_key.strip(),
    }

    max_attempts = 3
    delay_seconds = 0.5
    url = _build_brevo_url()

    # Retry only transient delivery failures.
    for attempt in range(1, max_attempts + 1):
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            if attempt == max_attempts:
                raise EmailDeliveryError(f"Failed to call Brevo API: {exc}") from exc
            await asyncio.sleep(delay_seconds * (2 ** (attempt - 1)))
            continue

        if response.status_code < 400:
            data = response.json() if response.content else {}
            message_id = data.get("messageId") if isinstance(data, dict) else None
            if isinstance(message_id, str) and message_id:
                return message_id
            return "unknown-message-id"

        if response.status_code == 429 or response.status_code >= 500:
            if attempt == max_attempts:
                detail = _extract_error_detail(response)
                raise EmailDeliveryError(
                    f"Brevo API temporary failure after retries: {detail}"
                )
            await asyncio.sleep(delay_seconds * (2 ** (attempt - 1)))
            continue

        detail = _extract_error_detail(response)
        raise EmailDeliveryError(f"Brevo API rejected email request: {detail}")

    raise EmailDeliveryError("Failed to send email.")
