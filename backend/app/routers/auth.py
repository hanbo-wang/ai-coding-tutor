"""Authentication endpoints: register, login, refresh, profile."""

import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.user import (
    ChangePassword,
    PasswordResetConfirmRequest,
    RegisterSendCodeRequest,
    RegisterWithCode,
    SendCodeRequest,
    TokenResponse,
    UserLogin,
    UserProfile,
    UserProfileUpdate,
)
from app.services.auth_service import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.services.email_service import EmailDeliveryError
from app.services.email_verification_service import (
    REGISTER_PURPOSE,
    RESET_PASSWORD_PURPOSE,
    ResendCooldownError,
    issue_email_verification_code,
    verify_email_verification_code,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Non-admin registrations must match a UCL student-style local part ending in digits.
UCL_STUDENT_REGISTRATION_EMAIL_PATTERN = re.compile(
    r"^[a-z0-9]+(?:\.[a-z0-9]+)*\.[0-9]+@ucl\.ac\.uk$"
)
REGISTRATION_EMAIL_POLICY_DETAIL = (
    "Registration is limited to UCL student emails in the format "
    "name.name.<digits>@ucl.ac.uk. Configured admin emails are exempt."
)


def set_refresh_cookie(response: Response, refresh_token: str) -> None:
    """Set the refresh token as an httpOnly cookie."""
    max_age_seconds = settings.jwt_refresh_token_expire_days * 24 * 60 * 60
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        path="/api/auth",
        max_age=max_age_seconds,
    )


def _integrity_error_detail(exc: IntegrityError) -> str | None:
    """Map common user integrity violations to client-safe messages."""
    detail = str(getattr(exc, "orig", exc)).lower()
    if "users.username" in detail or "ix_users_username" in detail:
        return "Username already taken"
    if "users.email" in detail or "ix_users_email" in detail:
        return "Email already registered"
    if "unique" in detail and "username" in detail:
        return "Username already taken"
    if "unique" in detail and "email" in detail:
        return "Email already registered"
    return None


def _validate_registration_email_or_raise(normalised_email: str) -> None:
    """Enforce the registration email policy, with an admin-email exemption."""
    if normalised_email in settings.admin_email_set:
        return
    if UCL_STUDENT_REGISTRATION_EMAIL_PATTERN.fullmatch(normalised_email):
        return
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=REGISTRATION_EMAIL_POLICY_DETAIL,
    )


@router.post("/register/send-code")
async def send_register_code(
    payload: RegisterSendCodeRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Send a registration verification code by email."""
    normalised_email = payload.email.lower()
    _validate_registration_email_or_raise(normalised_email)
    email_result = await db.execute(
        select(User).where(User.email == normalised_email)
    )
    if email_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )
    username_result = await db.execute(
        select(User).where(User.username == payload.username)
    )
    if username_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already taken",
        )

    try:
        # Only issue a code when both identity fields are still available.
        await issue_email_verification_code(
            db,
            email=normalised_email,
            purpose=REGISTER_PURPOSE,
        )
    except ResendCooldownError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Please wait {exc.retry_after_seconds}s before requesting another code.",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        )
    except EmailDeliveryError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to send verification email. Please try again.",
        )

    return {"message": "Verification code sent."}


@router.post("/register", response_model=TokenResponse)
async def register(
    user_data: RegisterWithCode,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Register a new user after verifying the email code."""
    normalised_email = user_data.email.lower()
    _validate_registration_email_or_raise(normalised_email)
    result = await db.execute(select(User).where(User.email == normalised_email))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )
    username_result = await db.execute(
        select(User).where(User.username == user_data.username)
    )
    if username_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already taken",
        )

    verified = await verify_email_verification_code(
        db,
        email=normalised_email,
        purpose=REGISTER_PURPOSE,
        code=user_data.verification_code,
    )
    if not verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification code",
        )

    user = User(
        email=normalised_email,
        username=user_data.username,
        password_hash=hash_password(user_data.password),
        programming_level=user_data.programming_level,
        maths_level=user_data.maths_level,
        is_admin=normalised_email in settings.admin_email_set,
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        detail = _integrity_error_detail(exc)
        if detail is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=detail,
            ) from exc
        raise
    await db.refresh(user)

    access_token = create_access_token(str(user.id))
    refresh_token = create_refresh_token(str(user.id))
    set_refresh_cookie(response, refresh_token)
    return TokenResponse(access_token=access_token)


@router.post("/login", response_model=TokenResponse)
async def login(
    credentials: UserLogin,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Authenticate user and return tokens."""
    result = await db.execute(
        select(User).where(User.email == credentials.email.lower())
    )
    user = result.scalar_one_or_none()
    if not user or not verify_password(credentials.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    access_token = create_access_token(str(user.id))
    refresh_token = create_refresh_token(str(user.id))
    set_refresh_cookie(response, refresh_token)

    return TokenResponse(access_token=access_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Refresh access token using the refresh token cookie."""
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token not found",
        )

    try:
        payload = decode_token(refresh_token)
        if payload.get("token_type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
            )
        user_id = payload.get("sub")
        user_uuid = uuid.UUID(user_id)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    access_token = create_access_token(str(user.id))
    new_refresh_token = create_refresh_token(str(user.id))
    set_refresh_cookie(response, new_refresh_token)

    return TokenResponse(access_token=access_token)


@router.post("/logout")
async def logout(response: Response):
    """Clear the refresh token cookie."""
    response.delete_cookie(key="refresh_token", path="/api/auth")
    return {"message": "Logged out successfully"}


@router.post("/password-reset/send-code")
async def send_password_reset_code(
    payload: SendCodeRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Send a password reset verification code for a registered email."""
    normalised_email = payload.email.lower()
    result = await db.execute(select(User).where(User.email == normalised_email))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email is not registered.",
        )

    try:
        await issue_email_verification_code(
            db,
            email=normalised_email,
            purpose=RESET_PASSWORD_PURPOSE,
        )
    except ResendCooldownError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Please wait {exc.retry_after_seconds}s before requesting another code.",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        )
    except EmailDeliveryError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to send verification email. Please try again.",
        )

    return {"message": "Verification code sent."}


@router.post("/password-reset/confirm")
async def confirm_password_reset(
    payload: PasswordResetConfirmRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Reset a password using a verified email code."""
    normalised_email = payload.email.lower()
    result = await db.execute(select(User).where(User.email == normalised_email))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email is not registered.",
        )

    verified = await verify_email_verification_code(
        db,
        email=normalised_email,
        purpose=RESET_PASSWORD_PURPOSE,
        code=payload.verification_code,
    )
    if not verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification code",
        )

    user.password_hash = hash_password(payload.new_password)
    await db.commit()
    return {"message": "Password reset successfully."}


@router.get("/me", response_model=UserProfile)
async def get_me(current_user: Annotated[User, Depends(get_current_user)]):
    """Get the current user's profile."""
    return current_user


@router.put("/me", response_model=UserProfile)
async def update_me(
    update_data: UserProfileUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Update the current user's profile (username, skill levels)."""
    username_updated = update_data.username is not None
    if update_data.username is not None:
        current_user.username = update_data.username

    if update_data.programming_level is not None:
        current_user.programming_level = update_data.programming_level
        current_user.effective_programming_level = float(update_data.programming_level)
    if update_data.maths_level is not None:
        current_user.maths_level = update_data.maths_level
        current_user.effective_maths_level = float(update_data.maths_level)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        detail = _integrity_error_detail(exc)
        if username_updated and detail == "Username already taken":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=detail,
            ) from exc
        raise
    await db.refresh(current_user)
    return current_user


@router.put("/me/password")
async def change_password(
    payload: ChangePassword,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Reset password for the signed-in user after checking current password."""
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect.",
        )

    current_user.password_hash = hash_password(payload.new_password)
    await db.commit()
    return {"message": "Password reset successfully."}
