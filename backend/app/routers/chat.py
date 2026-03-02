"""Chat router: REST endpoints and WebSocket handler for the AI tutor."""

import asyncio
import base64
import json
import logging
import uuid as uuid_mod
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.context_builder import (
    build_context_messages,
    build_system_prompt,
    build_single_pass_system_prompt,
)
from app.ai.llm_base import LLMError
from app.ai.llm_factory import (
    LLMTarget,
    build_llm_provider_for_target,
    get_llm_provider,
    list_llm_fallback_targets,
)
from app.ai.pricing import estimate_llm_cost_usd
from app.config import settings
from app.db.session import AsyncSessionLocal
from app.dependencies import get_current_user, get_db
from app.models.chat import UploadedFile
from app.models.user import User
from app.schemas.chat import ChatMessageIn, TokenUsageOut
from app.services import chat_service
from app.services.ai_services import get_ai_services
from app.services.auth_service import decode_token
from app.services.chat_summary_cache import chat_summary_cache_service
from app.services.connection_tracker import connection_tracker
from app.services.notebook_service import NotebookValidationError, refresh_extracted_text
from app.services.rate_limiter import rate_limiter
from app.services.stream_meta_parser import StreamMetaParser
from app.services.upload_service import get_upload_slot_limits, get_user_uploads_by_ids
from app.services.zone_service import get_zone_notebook_for_context

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])
GOOGLE_AI_STUDIO_PROVIDER = "google-aistudio"
GOOGLE_VERTEX_PROVIDER = "google-vertex"
GENERIC_LLM_UNAVAILABLE_ERROR = "AI service temporarily unavailable. Please try again."
FATAL_LLM_ERROR_MESSAGE = "Internal error. The administrator has been notified."
SAME_MODEL_RETRY_LIMIT = 5
SINGLE_PASS_PARSE_RETRY_LIMIT = 3

# Fatal error keywords that indicate non-transient LLM provider failures.
# When any of these appear in the exception text, the error is not retryable.
_FATAL_ERROR_KEYWORDS = (
    "400", "401", "403", "404",
    "api_key", "api key", "apikey",
    "unauthorized", "forbidden",
    "credential", "permission", "authentication",
    "invalid", "unsupported", "not found", "does not exist",
    "billing", "quota exceeded",
)

# In-memory ring buffer for recent LLM errors, read by the admin endpoint.
_LLM_ERROR_RING_MAX = 50
_llm_error_ring: deque[dict] = deque(maxlen=_LLM_ERROR_RING_MAX)


@dataclass
class _SessionRuntimeState:
    """Per-session hidden pedagogy runtime state for a single WebSocket connection."""

    student_state: "StudentState"
    single_pass_header_failure_streak: int = 0
    auto_degraded_to_two_step_recovery: bool = False
    two_step_recovery_turns_since_degrade: int = 0
    active_llm_target: LLMTarget | None = None


@dataclass
class _UsageSegment:
    """Token usage captured from one successful LLM call segment."""

    label: str
    provider: str
    model: str
    transport: str | None
    input_tokens: int
    output_tokens: int
    usage_details: dict


class _StageExecutionError(Exception):
    """Internal wrapper for a stage-level user-facing failure."""


# ── REST endpoints ──────────────────────────────────────────────────


@router.get("/api/chat/sessions")
async def list_sessions(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    session_type: str | None = Query(default=None),
    module_id: uuid_mod.UUID | None = Query(default=None),
):
    """Return chat sessions for one scope, newest first."""
    requested_type = (session_type or "general").strip().lower()
    if requested_type not in {"general", "notebook", "zone"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid session type.",
        )
    if requested_type in {"notebook", "zone"} and module_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="module_id is required for notebook and zone sessions.",
        )
    if requested_type == "general" and module_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="module_id is not supported for general sessions.",
        )
    return await chat_service.get_user_sessions(
        db,
        current_user.id,
        session_type=requested_type,
        module_id=module_id,
    )


@router.get("/api/chat/sessions/find")
async def find_session_by_scope(
    session_type: str,
    module_id: uuid_mod.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Return an existing scoped session for a notebook or zone module."""
    if session_type not in {"notebook", "zone"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid session type.",
        )
    session = await chat_service.get_session_by_scope(
        db, current_user.id, session_type, module_id
    )
    if session is None:
        return None
    return {
        "id": str(session.id),
        "session_type": session.session_type,
        "module_id": str(session.module_id) if session.module_id else None,
        "created_at": session.created_at.isoformat() if session.created_at else None,
    }


@router.delete("/api/chat/sessions/{session_id}")
async def delete_session(
    session_id: uuid_mod.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Delete a chat session and all its messages."""
    deleted = await chat_service.delete_session(db, current_user.id, session_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    await db.commit()
    return {"message": "Session deleted"}


@router.get("/api/chat/sessions/{session_id}/messages")
async def get_session_messages(
    session_id: uuid_mod.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Return all messages for a session in chronological order."""
    messages = await chat_service.get_session_messages(
        db, current_user.id, session_id
    )
    if messages is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    return messages


@router.get("/api/chat/usage", response_model=TokenUsageOut)
async def get_usage(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Return the current week's weighted token usage summary for the current user."""
    usage = await chat_service.get_weekly_usage_summary(db, current_user.id)
    weekly_limit = settings.user_weekly_weighted_token_limit
    usage_pct = (
        (usage.weighted_tokens_used / weekly_limit * 100) if weekly_limit > 0 else 0.0
    )
    weighted_used = round(usage.weighted_tokens_used, 1)
    remaining = round(max(0.0, float(weekly_limit) - usage.weighted_tokens_used), 1)
    return TokenUsageOut(
        week_start=usage.week_start,
        week_end=usage.week_end,
        input_tokens_used=usage.input_tokens_used,
        output_tokens_used=usage.output_tokens_used,
        weighted_tokens_used=weighted_used,
        remaining_weighted_tokens=remaining,
        weekly_weighted_limit=weekly_limit,
        usage_percentage=round(min(100.0, usage_pct), 1),
    )


# ── WebSocket helpers ───────────────────────────────────────────────


async def _authenticate_ws(token: str) -> User | None:
    """Validate a JWT token and return the user, or None."""
    try:
        payload = decode_token(token)
        if payload.get("token_type") != "access":
            return None
        user_id = payload.get("sub")
        if not user_id:
            return None
        user_uuid = uuid_mod.UUID(user_id)
    except ValueError:
        return None

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.id == user_uuid))
        return result.scalar_one_or_none()


async def _resolve_ws_token(websocket: WebSocket, query_token: str | None) -> str | None:
    """Resolve token from query string or initial auth frame."""
    if query_token:
        return query_token

    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=8)
    except (asyncio.TimeoutError, Exception):
        return None

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or payload.get("type") != "auth":
        return None
    token = payload.get("token")
    if not isinstance(token, str):
        return None
    stripped = token.strip()
    return stripped or None


def _split_uploads(
    uploads: list[UploadedFile],
) -> tuple[list[UploadedFile], list[UploadedFile]]:
    """Separate uploads into images and documents."""
    images: list[UploadedFile] = []
    documents: list[UploadedFile] = []
    for item in uploads:
        if item.file_type == "image":
            images.append(item)
        else:
            documents.append(item)
    return images, documents


def _validate_upload_mix(
    image_uploads: list[UploadedFile],
    document_uploads: list[UploadedFile],
) -> str | None:
    """Return an error message if upload limits are exceeded, else None."""
    max_images, max_documents = get_upload_slot_limits()
    if len(image_uploads) > max_images or len(document_uploads) > max_documents:
        return (
            f"Too many files. You can upload up to {max_images} photos and "
            f"{max_documents} files per message."
        )
    return None


def _build_enriched_message(
    user_message: str,
    document_uploads: list[UploadedFile],
) -> str:
    """Merge user text with extracted document content."""
    clean_text = user_message.strip()
    parts: list[str] = []
    if clean_text:
        parts.append(clean_text)
    for document in document_uploads:
        if document.extracted_text:
            parts.append(f"[Attached document: {document.original_filename}]\n{document.extracted_text}")
    if not parts:
        return "Please analyse the attached files."
    return "\n\n".join(parts)


def _build_multimodal_user_parts(
    enriched_message: str,
    image_uploads: list[UploadedFile],
) -> list[dict[str, str]]:
    """Construct multimodal message parts with base64 images."""
    parts: list[dict[str, str]] = [{"type": "text", "text": enriched_message}]
    for image in image_uploads:
        image_path = Path(image.storage_path)
        if not image_path.exists():
            continue
        b64_data = base64.b64encode(image_path.read_bytes()).decode("ascii")
        parts.append({
            "type": "image",
            "media_type": image.content_type,
            "data": b64_data,
        })
    return parts


def _truncate_text_by_tokens(llm, text: str, max_tokens: int) -> str:
    """Truncate text to fit within a token budget."""
    if max_tokens <= 0:
        return ""
    if llm.count_tokens(text) <= max_tokens:
        return text
    words = text.split()
    if not words:
        return ""
    kept: list[str] = []
    for word in words:
        candidate = " ".join(kept + [word])
        if llm.count_tokens(candidate) > max_tokens:
            break
        kept.append(word)
    return " ".join(kept)


def _build_notebook_context_block(
    llm,
    extracted_text: str,
    cell_code: str | None,
    error_output: str | None,
) -> str:
    """Format notebook content into a context block for the system prompt."""
    notebook_text = _truncate_text_by_tokens(
        llm, extracted_text.strip(), settings.notebook_max_context_tokens
    )
    if not notebook_text:
        notebook_text = "(Notebook has no extracted cell text.)"

    parts = ["--- Student's Notebook ---", notebook_text, "--- End of Notebook ---"]
    if cell_code:
        parts.extend(["", "--- Current Cell ---", cell_code, "--- End of Current Cell ---"])
    if error_output:
        parts.extend(["", "--- Error Output ---", error_output, "--- End of Error Output ---"])
    return "\n".join(parts)


def _build_single_pass_pedagogy_context(
    llm,
    student_state,
    fast_signals,
) -> str:
    """Build a hidden pedagogy context block for single-pass metadata + reply generation."""
    prev_question = (fast_signals.previous_question_text or "").strip()
    prev_answer = (fast_signals.previous_answer_text or "").strip()
    prev_question = _truncate_text_by_tokens(llm, prev_question, 500)
    prev_answer = _truncate_text_by_tokens(llm, prev_answer, 700)

    eff_prog = student_state.effective_programming_level
    eff_maths = student_state.effective_maths_level
    cur_prog_hint = student_state.current_programming_hint_level
    cur_maths_hint = student_state.current_maths_hint_level

    parts = [
        "--- Hidden Pedagogy Context (Do not reveal) ---",
        f"Effective programming level: {eff_prog:.2f}",
        f"Effective maths level: {eff_maths:.2f}",
        f"Current programming hint level: {cur_prog_hint}",
        f"Current maths hint level: {cur_maths_hint}",
        "",
        "HINT LEVEL FORMULA (follow exactly):",
        "New problem:",
        f"  prog_hint = max(1, min(4, 1 + (prog_difficulty - {round(eff_prog)})))",
        f"  maths_hint = max(1, min(4, 1 + (maths_difficulty - {round(eff_maths)})))",
        "Same problem:",
        f"  prog_hint = min(5, {cur_prog_hint} + 1) = {min(5, cur_prog_hint + 1)}",
        f"  maths_hint = min(5, {cur_maths_hint} + 1) = {min(5, cur_maths_hint + 1)}",
        "",
        "Your answer MUST obey both computed hint levels.",
    ]
    if fast_signals.has_previous_exchange:
        parts.extend(
            [
                "",
                "--- Previous Question ---",
                prev_question or "(empty)",
                "--- Previous Answer ---",
                prev_answer or "(empty)",
            ]
        )
    parts.append("--- End Hidden Pedagogy Context ---")
    return "\n".join(parts)


def _meta_event_payload(meta, session_id: str) -> dict[str, object]:
    """Format a `meta` websocket event payload from a pedagogy metadata object."""
    return {
        "type": "meta",
        "session_id": session_id,
        "programming_difficulty": meta.programming_difficulty,
        "maths_difficulty": meta.maths_difficulty,
        "programming_hint_level": meta.programming_hint_level,
        "maths_hint_level": meta.maths_hint_level,
        "same_problem": meta.same_problem,
        "is_elaboration": meta.is_elaboration,
        "source": meta.source,
    }


def _current_llm_runtime_signature() -> tuple[str, str, str]:
    """Return the active runtime LLM selection as a comparable tuple."""
    provider = settings.llm_provider
    models = {
        "anthropic": settings.llm_model_anthropic,
        "openai": settings.llm_model_openai,
        "google": settings.llm_model_google,
    }
    transport = settings.google_gemini_transport if provider == "google" else ""
    return provider, models.get(provider, ""), transport


def _llm_target_from_provider(llm) -> LLMTarget:
    """Build a comparable target tuple from a provider instance."""
    return LLMTarget(
        provider=str(llm.provider_id or "").strip().lower(),
        model_id=str(llm.model_id or "").strip(),
        google_transport=(
            str(getattr(llm, "runtime_transport", "") or "").strip().lower() or None
        ),
    )


def _runtime_usage_provider_id(
    provider_id: str,
    transport: str | None = None,
) -> str:
    """Return the provider id persisted to chat usage records."""
    canonical = str(provider_id or "").strip().lower()
    if canonical != "google":
        return canonical
    effective_transport = str(transport or "").strip().lower()
    if effective_transport == "aistudio":
        return GOOGLE_AI_STUDIO_PROVIDER
    if effective_transport == "vertex":
        return GOOGLE_VERTEX_PROVIDER
    return canonical


def _record_llm_error(
    *,
    provider: str,
    model: str,
    error_type: str,
    detail: str,
    stage: str = "",
) -> None:
    """Append an LLM error entry to the in-memory ring buffer."""
    _llm_error_ring.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "provider": provider,
        "model": model,
        "error_type": error_type,
        "detail": detail[:500],
        "stage": stage,
    })


def get_recent_llm_errors() -> list[dict]:
    """Return recent LLM errors, newest first. Used by the admin endpoint."""
    return list(reversed(_llm_error_ring))


def _user_facing_llm_error_message(
    exc: Exception,
    llm_provider_id: str,
    llm_transport: str | None = None,
) -> str:
    """Classify an LLM error as fatal or transient.

    Fatal errors (authentication, invalid API key, bad request, etc.) return a
    specific non-retryable message so the failover loop terminates immediately.
    Transient errors (timeouts, 429/5xx after provider-level retries) return the
    generic retryable message so the outer failover loop can retry or switch.
    """
    raw_detail = str(exc).strip()
    detail = raw_detail.lower()

    # Check for fatal keywords across all providers.
    is_fatal = any(keyword in detail for keyword in _FATAL_ERROR_KEYWORDS)

    provider_label = llm_provider_id or "unknown"
    model_label = ""

    if is_fatal:
        logger.error(
            "Fatal LLM error (provider=%s transport=%s): %s",
            llm_provider_id,
            llm_transport or "",
            raw_detail,
        )
        _record_llm_error(
            provider=provider_label,
            model=model_label,
            error_type="fatal",
            detail=raw_detail,
        )
        return FATAL_LLM_ERROR_MESSAGE

    # Transient error — log at warning level and allow retry.
    logger.warning(
        "Transient LLM error (provider=%s transport=%s): %s",
        llm_provider_id,
        llm_transport or "",
        raw_detail,
    )
    _record_llm_error(
        provider=provider_label,
        model=model_label,
        error_type="transient",
        detail=raw_detail,
    )
    return GENERIC_LLM_UNAVAILABLE_ERROR


def _is_retryable_unavailable_error(message: str) -> bool:
    """Only the generic transient message is retryable."""
    return message == GENERIC_LLM_UNAVAILABLE_ERROR


def _status_event_payload(
    *,
    stage: str,
    attempt: int,
    max_attempts: int,
    switched_model: bool = False,
    session_id: str,
) -> dict[str, object]:
    """Return websocket status payload for retries and model switching.

    `attempt` and `max_attempts` represent retry counts only, excluding the
    initial attempt.
    """
    if switched_model:
        message = (
            "Reconnecting to the AI service. "
            f"Switching to a fallback model for this session after {max_attempts} retries."
        )
    else:
        message = (
            f"Reconnecting to the AI service (retry {attempt} of {max_attempts})."
        )
    return {
        "type": "status",
        "session_id": session_id,
        "status": "reconnecting",
        "stage": stage,
        "attempt": attempt,
        "max_attempts": max_attempts,
        "switched_model": switched_model,
        "message": message,
    }


def _build_usage_segment(label: str, llm) -> _UsageSegment:
    """Capture one usage segment from the active provider."""
    return _UsageSegment(
        label=label,
        provider=str(llm.provider_id or "").strip().lower(),
        model=str(llm.model_id or "").strip(),
        transport=(str(getattr(llm, "runtime_transport", "") or "").strip().lower() or None),
        input_tokens=int(getattr(llm.last_usage, "input_tokens", 0) or 0),
        output_tokens=int(getattr(llm.last_usage, "output_tokens", 0) or 0),
        usage_details=dict(getattr(llm.last_usage, "usage_details", {}) or {}),
    )


# ── WebSocket endpoint ──────────────────────────────────────────────


@router.websocket("/ws/chat")
async def websocket_chat(
    websocket: WebSocket,
    token: str | None = Query(default=None),
):
    """WebSocket endpoint for the chat pipeline."""
    await websocket.accept()

    resolved_token = await _resolve_ws_token(websocket, token)
    user = await _authenticate_ws(resolved_token or "")
    if not user:
        await websocket.send_json({"type": "error", "message": "Authentication failed"})
        await websocket.close(code=4001, reason="Authentication failed")
        return

    user_id_str = str(user.id)
    conn_id = uuid_mod.uuid4().hex

    # Enforce concurrent connection limit.
    if not connection_tracker.can_connect(user_id_str):
        await websocket.send_json({"type": "error", "message": "Too many connections"})
        await websocket.close(code=4002, reason="Too many connections")
        return
    connection_tracker.add(user_id_str, conn_id)

    try:
        initial_llm = get_llm_provider(settings)
        llm_runtime_signature = _current_llm_runtime_signature()
        default_llm_target = _llm_target_from_provider(initial_llm)
    except Exception as exc:
        logger.error("Failed to initialise AI services: %s", exc)
        await websocket.send_json({"type": "error", "message": "Service unavailable"})
        connection_tracker.remove(user_id_str, conn_id)
        await websocket.close()
        return

    from app.ai.pedagogy_engine import StudentState

    def _new_session_runtime_state(db_user: User) -> _SessionRuntimeState:
        return _SessionRuntimeState(
            student_state=StudentState(
                user_id=user_id_str,
                effective_programming_level=(
                    db_user.effective_programming_level
                    if db_user.effective_programming_level is not None
                    else float(db_user.programming_level)
                ),
                effective_maths_level=(
                    db_user.effective_maths_level
                    if db_user.effective_maths_level is not None
                    else float(db_user.maths_level)
                ),
            ),
            auto_degraded_to_two_step_recovery=(
                settings.chat_metadata_route_mode == "two_step_recovery_route"
            ),
        )

    metadata_route_mode = settings.chat_metadata_route_mode
    single_pass_failures_before_two_step_recovery = max(
        1, int(settings.chat_single_pass_header_failures_before_two_step_recovery or 1)
    )
    two_step_recovery_turns_before_single_pass_retry = max(
        1, int(settings.chat_two_step_recovery_turns_before_single_pass_retry or 1)
    )
    session_runtime_states: dict[str, _SessionRuntimeState] = {}

    try:
        while True:
            raw = await websocket.receive_text()

            # Parse and validate the incoming message.
            try:
                data = json.loads(raw)
                if isinstance(data, dict) and data.get("type") == "auth":
                    continue
                payload = ChatMessageIn.model_validate(data)
            except (json.JSONDecodeError, ValidationError):
                await websocket.send_json({"type": "error", "message": "Invalid message format"})
                continue

            user_message = payload.content.strip()
            if not user_message and not payload.upload_ids:
                continue

            current_signature = _current_llm_runtime_signature()
            if current_signature != llm_runtime_signature:
                try:
                    switched_llm = get_llm_provider(settings)
                    default_llm_target = _llm_target_from_provider(switched_llm)
                    llm_runtime_signature = current_signature
                    logger.info(
                        "Applied runtime LLM switch to provider=%s model=%s transport=%s",
                        default_llm_target.provider,
                        default_llm_target.model_id,
                        default_llm_target.google_transport or "",
                    )
                except Exception as exc:
                    logger.error("Failed to apply runtime LLM switch: %s", exc)
                    await websocket.send_json({
                        "type": "error",
                        "message": "Model switch could not be applied right now. Please retry.",
                    })
                    continue

            # Enforce per user rate limit.
            if not rate_limiter.check_user(user_id_str):
                await websocket.send_json({
                    "type": "error",
                    "message": "Rate limit reached. Please wait before sending another message.",
                })
                continue

            # Enforce global rate limit.
            if not rate_limiter.check_global():
                await websocket.send_json({
                    "type": "error",
                    "message": "The service is busy. Please try again in a moment.",
                })
                continue

            upload_ids = payload.upload_ids
            notebook_id = payload.notebook_id
            zone_notebook_id = payload.zone_notebook_id
            cell_code = payload.cell_code.strip() if payload.cell_code else None
            error_output = payload.error_output.strip() if payload.error_output else None

            max_items = settings.upload_max_images_per_message + settings.upload_max_documents_per_message
            if len(upload_ids) > max_items:
                max_images, max_documents = get_upload_slot_limits()
                await websocket.send_json({
                    "type": "error",
                    "message": f"Too many files. You can upload up to {max_images} photos and {max_documents} files per message.",
                })
                continue

            if notebook_id and zone_notebook_id:
                await websocket.send_json({
                    "type": "error",
                    "message": "Only one notebook context can be sent per message.",
                })
                continue

            async with AsyncSessionLocal() as db:
                db_user_result = await db.execute(select(User).where(User.id == user.id))
                db_user = db_user_result.scalar_one_or_none()
                if db_user is None:
                    await websocket.send_json({"type": "error", "message": "Authentication failed"})
                    await websocket.close(code=4001, reason="Authentication failed")
                    return

                session_type = "general"
                module_id: uuid_mod.UUID | None = None
                notebook_extracted_text: str | None = None
                notebook_context: str | None = None

                # Resolve notebook context.
                if notebook_id:
                    try:
                        extracted_text = await refresh_extracted_text(db, user.id, notebook_id)
                    except NotebookValidationError as exc:
                        await websocket.send_json({"type": "error", "session_id": str(session.id), "message": str(exc)})
                        continue
                    if extracted_text is None:
                        await websocket.send_json({"type": "error", "message": "Notebook not found."})
                        continue
                    notebook_extracted_text = extracted_text
                    session_type = "notebook"
                    module_id = notebook_id
                elif zone_notebook_id:
                    zone_notebook = await get_zone_notebook_for_context(db, zone_notebook_id)
                    if zone_notebook is None:
                        await websocket.send_json({"type": "error", "message": "Zone notebook not found."})
                        continue
                    notebook_extracted_text = zone_notebook.extracted_text or ""
                    session_type = "zone"
                    module_id = zone_notebook_id

                # Resolve and validate uploads.
                uploads = await get_user_uploads_by_ids(db, user.id, upload_ids)
                if len(uploads) != len(upload_ids):
                    await websocket.send_json({
                        "type": "error",
                        "message": "One or more attachments are invalid, expired, or inaccessible.",
                    })
                    continue

                image_uploads, document_uploads = _split_uploads(uploads)
                mix_error = _validate_upload_mix(image_uploads, document_uploads)
                if mix_error:
                    await websocket.send_json({"type": "error", "message": mix_error})
                    continue

                enriched_user_message = _build_enriched_message(user_message, document_uploads)

                session = await chat_service.get_or_create_session(
                    db,
                    user.id,
                    session_id=payload.session_id,
                    session_type=session_type,
                    module_id=module_id,
                )
                session_key = str(session.id)
                runtime_state = session_runtime_states.get(session_key)
                if runtime_state is None:
                    runtime_state = _new_session_runtime_state(db_user)
                    session_runtime_states[session_key] = runtime_state
                student_state = runtime_state.student_state
                student_state.effective_programming_level = (
                    db_user.effective_programming_level
                    if db_user.effective_programming_level is not None
                    else float(db_user.programming_level)
                )
                student_state.effective_maths_level = (
                    db_user.effective_maths_level
                    if db_user.effective_maths_level is not None
                    else float(db_user.maths_level)
                )

                active_target = runtime_state.active_llm_target
                active_llm = None
                active_pedagogy_engine = None

                # For a fresh scoped session, keep the already-resolved runtime provider.
                # This avoids rebuilding through factory paths before we even need retries.
                if active_target is None:
                    try:
                        active_llm = get_llm_provider(settings)
                        active_pedagogy_engine = await get_ai_services(active_llm)
                        active_target = _llm_target_from_provider(active_llm)
                    except Exception as exc:
                        logger.error("Failed to resolve initial LLM for session: %s", exc)
                        await websocket.send_json(
                            {"type": "error", "message": GENERIC_LLM_UNAVAILABLE_ERROR}
                        )
                        await db.commit()
                        continue

                if active_target is None:
                    active_target = default_llm_target

                candidate_targets = [active_target] + list_llm_fallback_targets(
                    settings,
                    current_provider=active_target.provider,
                    current_model=active_target.model_id,
                    current_google_transport=active_target.google_transport,
                )
                resolved_initial_target = active_target

                if active_llm is None or active_pedagogy_engine is None:
                    for idx, candidate_target in enumerate(candidate_targets):
                        try:
                            active_llm = build_llm_provider_for_target(
                                settings, candidate_target
                            )
                            active_pedagogy_engine = await get_ai_services(active_llm)
                            resolved_initial_target = candidate_target
                            if idx > 0:
                                await websocket.send_json(
                                    _status_event_payload(
                                        stage="session_initialisation",
                                        attempt=1,
                                        max_attempts=SAME_MODEL_RETRY_LIMIT,
                                        switched_model=True,
                                        session_id=str(session.id),
                                    )
                                )
                            break
                        except Exception:
                            continue
                if active_llm is None or active_pedagogy_engine is None:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "message": GENERIC_LLM_UNAVAILABLE_ERROR,
                        }
                    )
                    await db.commit()
                    continue
                active_target = resolved_initial_target
                candidate_targets = [active_target] + list_llm_fallback_targets(
                    settings,
                    current_provider=active_target.provider,
                    current_model=active_target.model_id,
                    current_google_transport=active_target.google_transport,
                )

                if notebook_extracted_text is not None:
                    notebook_context = _build_notebook_context_block(
                        active_llm,
                        notebook_extracted_text,
                        cell_code,
                        error_output,
                    )

                # Pre-call estimate for input guard (reject obviously oversized messages).
                estimated_input = active_llm.count_tokens(enriched_user_message) + (
                    len(image_uploads) * settings.image_token_estimate
                )
                if estimated_input > settings.llm_max_user_input_tokens:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Files are too large for one message. Please split them and try again.",
                    })
                    continue

                # Pre-call weekly budget check (precise recording happens after API call).
                if not await chat_service.check_weekly_limit(db, user.id):
                    await websocket.send_json({
                        "type": "error",
                        "message": "Weekly token allowance reached. Please try again next week.",
                    })
                    continue

                stored_content = user_message if user_message else "Sent attachments."
                await chat_service.save_message(
                    db, session.id, "user", stored_content,
                    attachment_ids=[str(item.id) for item in uploads],
                )
                await db.commit()

                await websocket.send_json({"type": "session", "session_id": str(session.id)})

                # Run pedagogy pipeline.
                fast_signals = await active_pedagogy_engine.prepare_fast_signals(
                    enriched_user_message,
                    student_state,
                    username=db_user.username,
                )

                # Record the request for rate limiting (counted when LLM is called).
                rate_limiter.record(user_id_str)

                chat_history = await chat_service.get_chat_history(db, session.id)
                if chat_history:
                    chat_history = chat_history[:-1]

                summary_cache = chat_service.get_summary_cache_snapshot(session)
                use_two_step_recovery_route = bool(
                    metadata_route_mode == "two_step_recovery_route"
                    or (
                        metadata_route_mode == "auto"
                        and runtime_state.auto_degraded_to_two_step_recovery
                    )
                )

                messages = await build_context_messages(
                    chat_history=chat_history,
                    user_message=enriched_user_message,
                    llm=active_llm,
                    max_context_tokens=settings.llm_max_context_tokens,
                    compression_threshold=settings.context_compression_threshold,
                    cached_summary=summary_cache.text,
                    cached_summary_message_count=summary_cache.message_count,
                    allow_inline_compression=False,
                )
                if image_uploads and messages:
                    messages[-1] = {
                        "role": "user",
                        "content": _build_multimodal_user_parts(enriched_user_message, image_uploads),
                    }

                full_response: list[str] = []
                stream_meta = None
                single_pass_meta_source: str | None = None
                single_pass_parse_failed = False
                single_pass_parse_failure_reason: str | None = None
                current_candidate_index = 0
                current_llm = active_llm
                current_pedagogy_engine = active_pedagogy_engine
                usage_segments: list[_UsageSegment] = []
                final_reply_target = _llm_target_from_provider(active_llm)
                primary_candidate_target = active_target
                primary_candidate_llm = active_llm
                primary_candidate_pedagogy_engine = active_pedagogy_engine

                async def _activate_candidate(index: int):
                    nonlocal current_llm, current_pedagogy_engine, current_candidate_index
                    if index == 0:
                        current_candidate_index = 0
                        current_llm = primary_candidate_llm
                        current_pedagogy_engine = primary_candidate_pedagogy_engine
                        return (
                            primary_candidate_llm,
                            primary_candidate_pedagogy_engine,
                            primary_candidate_target,
                        )
                    target = candidate_targets[index]
                    llm_candidate = build_llm_provider_for_target(settings, target)
                    pedagogy_candidate = await get_ai_services(llm_candidate)
                    current_candidate_index = index
                    current_llm = llm_candidate
                    current_pedagogy_engine = pedagogy_candidate
                    return llm_candidate, pedagogy_candidate, target

                async def _run_stage_with_failover(
                    *,
                    stage_label: str,
                    runner,
                    has_visible_output,
                ):
                    nonlocal current_candidate_index
                    same_model_retry_count = 0
                    while True:
                        try:
                            llm_candidate, pedagogy_candidate, _ = await _activate_candidate(
                                current_candidate_index
                            )
                            result_value = await runner(llm_candidate, pedagogy_candidate)
                            usage_segments.append(
                                _build_usage_segment(stage_label, llm_candidate)
                            )
                            return result_value, llm_candidate, pedagogy_candidate
                        except Exception as exc:
                            # Evaluate whether to provide a specific LLM error or a generic fallback
                            if isinstance(exc, LLMError):
                                message = _user_facing_llm_error_message(
                                    exc,
                                    str(getattr(current_llm, "provider_id", "") or ""),
                                    str(getattr(current_llm, "runtime_transport", "") or ""),
                                )
                            else:
                                message = str(exc).strip() or GENERIC_LLM_UNAVAILABLE_ERROR

                            # If the error is not a transient availability issue, or if the client
                            # has already received visible tokens, we cannot safely retry invisibly.
                            if (
                                not _is_retryable_unavailable_error(message)
                                or has_visible_output()
                            ):
                                raise _StageExecutionError(message) from exc

                            # Attempt a retry using the current model if under the limit
                            if same_model_retry_count < SAME_MODEL_RETRY_LIMIT:
                                same_model_retry_count += 1
                                await websocket.send_json(
                                    _status_event_payload(
                                        stage=stage_label,
                                        attempt=same_model_retry_count,
                                        max_attempts=SAME_MODEL_RETRY_LIMIT,
                                        switched_model=False,
                                        session_id=str(session.id),
                                    )
                                )
                                continue

                            # If the same-model retries are exhausted, attempt to fall back to the next candidate model
                            if current_candidate_index + 1 < len(candidate_targets):
                                await websocket.send_json(
                                    _status_event_payload(
                                        stage=stage_label,
                                        attempt=SAME_MODEL_RETRY_LIMIT,
                                        max_attempts=SAME_MODEL_RETRY_LIMIT,
                                        switched_model=True,
                                        session_id=str(session.id),
                                    )
                                )
                                current_candidate_index += 1
                                same_model_retry_count = 0
                                continue

                            # All gracefully handled retry paths have failed
                            raise _StageExecutionError(message) from exc

                async def _stream_visible_reply(
                    llm_for_stage,
                    *,
                    system_prompt: str,
                    visible_state: dict[str, bool],
                ) -> list[str]:
                    parts: list[str] = []
                    async for chunk in llm_for_stage.generate_stream(
                        system_prompt=system_prompt,
                        messages=messages,
                    ):
                        if not chunk:
                            continue
                        visible_state["sent"] = True
                        parts.append(chunk)
                        await websocket.send_json({"type": "token", "session_id": str(session.id), "content": chunk})
                    return parts

                try:
                    if use_two_step_recovery_route:
                        stream_meta, _, _ = await _run_stage_with_failover(
                            stage_label="two_step_recovery_meta",
                            runner=lambda _llm, pedagogy: pedagogy.classify_two_step_recovery_meta(
                                enriched_user_message,
                                student_state=student_state,
                                fast_signals=fast_signals,
                            ),
                            has_visible_output=lambda: False,
                        )
                        await websocket.send_json(_meta_event_payload(stream_meta, str(session.id)))
                        single_pass_meta_source = stream_meta.source
                        visible_state = {"sent": False}
                        system_prompt = build_system_prompt(
                            programming_hint_level=stream_meta.programming_hint_level,
                            maths_hint_level=stream_meta.maths_hint_level,
                            programming_level=round(student_state.effective_programming_level),
                            maths_level=round(student_state.effective_maths_level),
                            notebook_context=notebook_context,
                        )
                        full_response, reply_llm, _ = await _run_stage_with_failover(
                            stage_label="two_step_recovery_reply",
                            runner=lambda llm_for_stage, _pedagogy: _stream_visible_reply(
                                llm_for_stage,
                                system_prompt=system_prompt,
                                visible_state=visible_state,
                            ),
                            has_visible_output=lambda: visible_state["sent"],
                        )
                        final_reply_target = _llm_target_from_provider(reply_llm)
                    else:
                        single_pass_success = False

                        async def _single_pass_stream_attempt(
                            llm_for_stage,
                            pedagogy_for_stage,
                            visible_state: dict[str, bool],
                        ):
                            parser = StreamMetaParser()
                            single_pass_visible_chunks: list[str] = []
                            meta_sent = False
                            attempt_stream_meta = None
                            attempt_meta_source: str | None = None
                            attempt_parse_failed = False
                            attempt_parse_failure_reason: str | None = None
                            async def _handle_parser_output(parsed) -> None:
                                nonlocal attempt_stream_meta, meta_sent, attempt_meta_source
                                nonlocal attempt_parse_failed, attempt_parse_failure_reason

                                if (
                                    parsed.meta_parsed
                                    and parsed.meta is not None
                                    and attempt_stream_meta is None
                                ):
                                    try:
                                        attempt_stream_meta = pedagogy_for_stage.coerce_stream_meta(
                                            parsed.meta,
                                            student_state=student_state,
                                            fast_signals=fast_signals,
                                            source="single_pass_header_route",
                                        )
                                        attempt_meta_source = attempt_stream_meta.source
                                        if not meta_sent:
                                            await websocket.send_json(
                                                _meta_event_payload(attempt_stream_meta, str(session.id))
                                            )
                                            meta_sent = True
                                    except Exception as exc:
                                        attempt_parse_failed = True
                                        attempt_parse_failure_reason = "invalid_header_json"
                                        logger.warning(
                                            "Invalid Single-Pass Header Route metadata; "
                                            "discarding output and recovering: %s",
                                            exc,
                                        )
                                        attempt_stream_meta = None
                                        meta_sent = False

                                if parsed.parse_error_reason:
                                    attempt_parse_failed = True
                                    if attempt_parse_failure_reason is None:
                                        attempt_parse_failure_reason = parsed.parse_error_reason
                                    logger.warning(
                                        "Single-Pass Header Route parse failure (%s); "
                                        "discarding output and recovering",
                                        parsed.parse_error_reason,
                                    )

                                for body_chunk in parsed.body_chunks:
                                    if not body_chunk:
                                        continue
                                    if attempt_parse_failed:
                                        continue
                                    if attempt_stream_meta is None:
                                        attempt_parse_failed = True
                                        attempt_parse_failure_reason = (
                                            attempt_parse_failure_reason
                                            or "missing_or_unparsed_header"
                                        )
                                        logger.warning(
                                            "Single-Pass Header Route body arrived before "
                                            "valid metadata; discarding output and recovering"
                                        )
                                        continue
                                    if not meta_sent:
                                        await websocket.send_json(
                                            _meta_event_payload(attempt_stream_meta, str(session.id))
                                        )
                                        meta_sent = True
                                    visible_state["sent"] = True
                                    single_pass_visible_chunks.append(body_chunk)
                                    await websocket.send_json(
                                        {"type": "token", "session_id": str(session.id), "content": body_chunk}
                                    )

                            async for chunk in llm_for_stage.generate_stream(
                                system_prompt=build_single_pass_system_prompt(
                                    programming_level=round(
                                        student_state.effective_programming_level
                                    ),
                                    maths_level=round(student_state.effective_maths_level),
                                    pedagogy_context=_build_single_pass_pedagogy_context(
                                        llm_for_stage,
                                        student_state,
                                        fast_signals,
                                    ),
                                    notebook_context=notebook_context,
                                ),
                                messages=messages,
                            ):
                                await _handle_parser_output(parser.feed(chunk))
                            await _handle_parser_output(parser.finalize())

                            return {
                                "meta": attempt_stream_meta,
                                "meta_source": attempt_meta_source,
                                "parse_failed": attempt_parse_failed,
                                "parse_failure_reason": attempt_parse_failure_reason,
                                "visible_chunks": single_pass_visible_chunks,
                                "visible_sent": visible_state["sent"],
                            }

                        for parse_retry_index in range(SINGLE_PASS_PARSE_RETRY_LIMIT + 1):
                            single_pass_visible_state = {"sent": False}
                            single_pass_result, single_pass_llm, _ = await _run_stage_with_failover(
                                stage_label="single_pass_header_route",
                                runner=lambda llm_for_stage, pedagogy_for_stage: _single_pass_stream_attempt(
                                    llm_for_stage,
                                    pedagogy_for_stage,
                                    single_pass_visible_state,
                                ),
                                has_visible_output=lambda: single_pass_visible_state["sent"],
                            )
                            if (
                                not single_pass_result["parse_failed"]
                                and single_pass_result["meta"] is not None
                                and single_pass_result["meta_source"]
                                == "single_pass_header_route"
                            ):
                                stream_meta = single_pass_result["meta"]
                                single_pass_meta_source = single_pass_result["meta_source"]
                                single_pass_parse_failed = False
                                full_response = list(single_pass_result["visible_chunks"])
                                final_reply_target = _llm_target_from_provider(single_pass_llm)
                                single_pass_success = True
                                break

                            single_pass_parse_failed = True
                            single_pass_parse_failure_reason = single_pass_result[
                                "parse_failure_reason"
                            ] or "header_parse_failure"

                            if single_pass_result["visible_sent"]:
                                raise _StageExecutionError(GENERIC_LLM_UNAVAILABLE_ERROR)

                            if parse_retry_index < SINGLE_PASS_PARSE_RETRY_LIMIT:
                                await websocket.send_json(
                                    _status_event_payload(
                                        stage="single_pass_header_meta",
                                        attempt=parse_retry_index + 1,
                                        max_attempts=SINGLE_PASS_PARSE_RETRY_LIMIT,
                                        switched_model=False,
                                        session_id=str(session.id),
                                    )
                                )

                        if not single_pass_success:
                            stream_meta, _, _ = await _run_stage_with_failover(
                                stage_label="two_step_recovery_meta",
                                runner=lambda _llm, pedagogy: pedagogy.classify_two_step_recovery_meta(
                                    enriched_user_message,
                                    student_state=student_state,
                                    fast_signals=fast_signals,
                                ),
                                has_visible_output=lambda: False,
                            )
                            await websocket.send_json(_meta_event_payload(stream_meta, str(session.id)))
                            single_pass_meta_source = stream_meta.source
                            visible_state = {"sent": False}
                            recovery_system_prompt = build_system_prompt(
                                programming_hint_level=stream_meta.programming_hint_level,
                                maths_hint_level=stream_meta.maths_hint_level,
                                programming_level=round(student_state.effective_programming_level),
                                maths_level=round(student_state.effective_maths_level),
                                notebook_context=notebook_context,
                            )
                            full_response, reply_llm, _ = await _run_stage_with_failover(
                                stage_label="two_step_recovery_reply",
                                runner=lambda llm_for_stage, _pedagogy: _stream_visible_reply(
                                    llm_for_stage,
                                    system_prompt=recovery_system_prompt,
                                    visible_state=visible_state,
                                ),
                                has_visible_output=lambda: visible_state["sent"],
                            )
                            final_reply_target = _llm_target_from_provider(reply_llm)
                except _StageExecutionError as exc:
                    logger.error("LLM stage error: %s", exc)
                    await websocket.send_json({"type": "error", "session_id": str(session.id), "message": str(exc)})
                    await db.commit()
                    # Stage failures are terminal for this socket lifecycle.
                    await websocket.close(code=1011, reason="LLM stage error")
                    return

                assistant_text = "".join(full_response)
                result = current_pedagogy_engine.apply_stream_meta(student_state, stream_meta)

                if not use_two_step_recovery_route and metadata_route_mode == "auto":
                    if (
                        single_pass_meta_source == "single_pass_header_route"
                        and not single_pass_parse_failed
                    ):
                        runtime_state.single_pass_header_failure_streak = 0
                    else:
                        runtime_state.single_pass_header_failure_streak += 1
                        if (
                            not runtime_state.auto_degraded_to_two_step_recovery
                            and runtime_state.single_pass_header_failure_streak
                            >= single_pass_failures_before_two_step_recovery
                        ):
                            runtime_state.auto_degraded_to_two_step_recovery = True
                            runtime_state.two_step_recovery_turns_since_degrade = 0
                            logger.warning(
                                "Auto-degrading chat metadata route to the Two-Step Recovery Route "
                                "after %d consecutive header parse failures",
                                runtime_state.single_pass_header_failure_streak,
                            )
                elif (
                    use_two_step_recovery_route
                    and metadata_route_mode == "auto"
                    and runtime_state.auto_degraded_to_two_step_recovery
                ):
                    if getattr(stream_meta, "source", None) == "two_step_recovery_route":
                        runtime_state.two_step_recovery_turns_since_degrade += 1
                    else:
                        runtime_state.two_step_recovery_turns_since_degrade = 0
                    if (
                        runtime_state.two_step_recovery_turns_since_degrade
                        >= two_step_recovery_turns_before_single_pass_retry
                    ):
                        runtime_state.auto_degraded_to_two_step_recovery = False
                        runtime_state.two_step_recovery_turns_since_degrade = 0
                        runtime_state.single_pass_header_failure_streak = 0
                        logger.info(
                            "Auto mode retrying the Single-Pass Header Route "
                            "after %d successful Two-Step Recovery Route turns",
                            two_step_recovery_turns_before_single_pass_retry,
                        )

                # Use precise token counts from all successful route segments in this turn.
                input_tokens = sum(max(0, int(seg.input_tokens or 0)) for seg in usage_segments)
                output_tokens = sum(max(0, int(seg.output_tokens or 0)) for seg in usage_segments)
                final_usage_segment = usage_segments[-1] if usage_segments else None
                usage_details = (
                    dict(final_usage_segment.usage_details or {})
                    if final_usage_segment is not None
                    else {}
                )
                usage_details["segments"] = [
                    {
                        "label": segment.label,
                        "provider": segment.provider,
                        "model": segment.model,
                        "transport": segment.transport,
                        "input_tokens": segment.input_tokens,
                        "output_tokens": segment.output_tokens,
                        "usage_details": segment.usage_details,
                    }
                    for segment in usage_segments
                ]
                if single_pass_parse_failed:
                    usage_details["single_pass_parse_failure_reason"] = (
                        single_pass_parse_failure_reason or "header_parse_failure"
                    )

                estimated_cost_usd = 0.0
                segment_costs: list[dict[str, object]] = []
                for segment in usage_segments:
                    segment_cost = estimate_llm_cost_usd(
                        segment.provider,
                        segment.model,
                        segment.input_tokens,
                        segment.output_tokens,
                        usage_details=segment.usage_details,
                    )
                    estimated_cost_usd += segment_cost
                    segment_costs.append(
                        {
                            "label": segment.label,
                            "provider": segment.provider,
                            "model": segment.model,
                            "transport": segment.transport,
                            "estimated_cost_usd": segment_cost,
                        }
                    )
                estimated_cost_usd = round(estimated_cost_usd, 4)
                usage_details["segment_costs"] = segment_costs

                runtime_state.active_llm_target = final_reply_target

                current_pedagogy_engine.update_previous_exchange_text(
                    student_state, enriched_user_message, assistant_text
                )

                # Update the user message with precise input tokens.
                await chat_service.save_message(
                    db, session.id, "assistant", assistant_text,
                    programming_difficulty=result.programming_difficulty,
                    maths_difficulty=result.maths_difficulty,
                    programming_hint_level_used=result.programming_hint_level,
                    maths_hint_level_used=result.maths_hint_level,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    llm_provider=_runtime_usage_provider_id(
                        final_reply_target.provider,
                        final_reply_target.google_transport,
                    ),
                    llm_model=final_reply_target.model_id,
                    estimated_cost_usd=estimated_cost_usd,
                    llm_usage=usage_details,
                )

                # Record precise usage to daily totals.
                await chat_service.record_token_usage(db, user.id, input_tokens, output_tokens)

                db_user.effective_programming_level = student_state.effective_programming_level
                db_user.effective_maths_level = student_state.effective_maths_level

                await db.commit()

                await websocket.send_json({
                    "type": "done",
                    "session_id": str(session.id),
                    "programming_difficulty": result.programming_difficulty,
                    "maths_difficulty": result.maths_difficulty,
                    "programming_hint_level": result.programming_hint_level,
                    "maths_hint_level": result.maths_hint_level,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                })
                chat_summary_cache_service.schedule_refresh(session.id)

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for user %s", user.id)
    except Exception as exc:
        logger.error("WebSocket error: %s", exc)
        try:
            await websocket.send_json({"type": "error", "message": "Internal error"})
            await websocket.close()
        except Exception:
            pass
    finally:
        connection_tracker.remove(user_id_str, conn_id)
