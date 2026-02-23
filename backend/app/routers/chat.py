"""Chat router: REST endpoints and WebSocket handler for the AI tutor."""

import asyncio
import base64
import json
import logging
import uuid as uuid_mod
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

from app.ai.context_builder import build_context_messages, build_system_prompt
from app.ai.llm_base import LLMError
from app.ai.llm_factory import get_llm_provider
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
from app.services.connection_tracker import connection_tracker
from app.services.notebook_service import NotebookValidationError, refresh_extracted_text
from app.services.rate_limiter import rate_limiter
from app.services.upload_service import get_upload_slot_limits, get_user_uploads_by_ids
from app.services.zone_service import get_zone_notebook_for_context

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


# ── REST endpoints ──────────────────────────────────────────────────


@router.get("/api/chat/sessions")
async def list_sessions(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Return all chat sessions for the current user, newest first."""
    return await chat_service.get_user_sessions(db, current_user.id)


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


async def _build_combined_embedding(embedding_service, enriched_message, image_uploads):
    """Generate a combined text and image embedding vector."""
    vectors: list[list[float]] = []
    text_embedding = await embedding_service.embed_text(enriched_message)
    if text_embedding:
        vectors.append(text_embedding)
    for image in image_uploads:
        image_path = Path(image.storage_path)
        if not image_path.exists():
            continue
        image_embedding = await embedding_service.embed_image(
            image_path.read_bytes(), image.content_type
        )
        if image_embedding:
            vectors.append(image_embedding)
    return embedding_service.combine_embeddings(vectors)


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
        llm = get_llm_provider(settings)
        embedding_service, pedagogy_engine = await get_ai_services(llm)
    except Exception as exc:
        logger.error("Failed to initialise AI services: %s", exc)
        await websocket.send_json({"type": "error", "message": "Service unavailable"})
        connection_tracker.remove(user_id_str, conn_id)
        await websocket.close()
        return

    from app.ai.pedagogy_engine import StudentState
    student_state = StudentState(
        user_id=user_id_str,
        effective_programming_level=(
            user.effective_programming_level
            if user.effective_programming_level is not None
            else float(user.programming_level)
        ),
        effective_maths_level=(
            user.effective_maths_level
            if user.effective_maths_level is not None
            else float(user.maths_level)
        ),
    )

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
                session_type = "general"
                module_id: uuid_mod.UUID | None = None
                notebook_context: str | None = None

                # Resolve notebook context.
                if notebook_id:
                    try:
                        extracted_text = await refresh_extracted_text(db, user.id, notebook_id)
                    except NotebookValidationError as exc:
                        await websocket.send_json({"type": "error", "message": str(exc)})
                        continue
                    if extracted_text is None:
                        await websocket.send_json({"type": "error", "message": "Notebook not found."})
                        continue
                    notebook_context = _build_notebook_context_block(llm, extracted_text, cell_code, error_output)
                    session_type = "notebook"
                    module_id = notebook_id
                elif zone_notebook_id:
                    zone_notebook = await get_zone_notebook_for_context(db, zone_notebook_id)
                    if zone_notebook is None:
                        await websocket.send_json({"type": "error", "message": "Zone notebook not found."})
                        continue
                    notebook_context = _build_notebook_context_block(
                        llm, zone_notebook.extracted_text or "", cell_code, error_output,
                    )
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

                # Pre-call estimate for input guard (reject obviously oversized messages).
                estimated_input = llm.count_tokens(enriched_user_message) + (
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

                combined_embedding = await _build_combined_embedding(
                    embedding_service, enriched_user_message, image_uploads
                )

                session = await chat_service.get_or_create_session(
                    db, user.id,
                    session_id=payload.session_id,
                    session_type=session_type,
                    module_id=module_id,
                )

                stored_content = user_message if user_message else "Sent attachments."
                await chat_service.save_message(
                    db, session.id, "user", stored_content,
                    attachment_ids=[str(item.id) for item in uploads],
                )
                await db.commit()

                await websocket.send_json({"type": "session", "session_id": str(session.id)})

                # Run pedagogy pipeline.
                has_notebook_context = bool(notebook_id or zone_notebook_id)
                topic_filters_allowed = (not bool(uploads)) and (not has_notebook_context)
                result = await pedagogy_engine.process_message(
                    enriched_user_message,
                    student_state,
                    username=user.username,
                    embedding_override=combined_embedding,
                    enable_greeting_filter=(
                        topic_filters_allowed and settings.chat_enable_greeting_filter
                    ),
                    enable_off_topic_filter=(
                        topic_filters_allowed and settings.chat_enable_off_topic_filter
                    ),
                )

                if result.filter_result:
                    await websocket.send_json({
                        "type": "canned",
                        "content": result.canned_response,
                        "filter": result.filter_result,
                    })
                    await chat_service.save_message(db, session.id, "assistant", result.canned_response or "")
                    await db.commit()
                    continue

                # Record the request for rate limiting (counted when LLM is called).
                rate_limiter.record(user_id_str)

                chat_history = await chat_service.get_chat_history(db, session.id)
                if chat_history:
                    chat_history = chat_history[:-1]

                system_prompt = build_system_prompt(
                    hint_level=result.hint_level or 1,
                    programming_level=round(student_state.effective_programming_level),
                    maths_level=round(student_state.effective_maths_level),
                    notebook_context=notebook_context,
                )

                messages = await build_context_messages(
                    chat_history=chat_history,
                    user_message=enriched_user_message,
                    llm=llm,
                    max_context_tokens=settings.llm_max_context_tokens,
                    compression_threshold=settings.context_compression_threshold,
                )
                if image_uploads and messages:
                    messages[-1] = {
                        "role": "user",
                        "content": _build_multimodal_user_parts(enriched_user_message, image_uploads),
                    }

                # Stream LLM response.
                full_response: list[str] = []
                try:
                    async for chunk in llm.generate_stream(
                        system_prompt=system_prompt, messages=messages,
                    ):
                        full_response.append(chunk)
                        await websocket.send_json({"type": "token", "content": chunk})
                except LLMError as exc:
                    logger.error("LLM error: %s", exc)
                    await websocket.send_json({
                        "type": "error",
                        "message": "AI service temporarily unavailable. Please try again.",
                    })
                    await db.commit()
                    continue

                assistant_text = "".join(full_response)

                # Use precise token counts from the API response.
                input_tokens = llm.last_usage.input_tokens
                output_tokens = llm.last_usage.output_tokens
                usage_details = llm.last_usage.usage_details or {}
                estimated_cost_usd = estimate_llm_cost_usd(
                    llm.provider_id,
                    llm.model_id,
                    input_tokens,
                    output_tokens,
                    usage_details=usage_details,
                )

                await pedagogy_engine.update_context_embedding(
                    student_state, enriched_user_message, assistant_text,
                    question_embedding=combined_embedding,
                )

                # Update the user message with precise input tokens.
                await chat_service.save_message(
                    db, session.id, "assistant", assistant_text,
                    hint_level_used=result.hint_level,
                    problem_difficulty=result.programming_difficulty,
                    maths_difficulty=result.maths_difficulty,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    llm_provider=llm.provider_id,
                    llm_model=llm.model_id,
                    estimated_cost_usd=estimated_cost_usd,
                    llm_usage=usage_details,
                )

                # Record precise usage to daily totals.
                await chat_service.record_token_usage(db, user.id, input_tokens, output_tokens)

                db_user_result = await db.execute(select(User).where(User.id == user.id))
                db_user = db_user_result.scalar_one_or_none()
                if db_user:
                    db_user.effective_programming_level = student_state.effective_programming_level
                    db_user.effective_maths_level = student_state.effective_maths_level

                await db.commit()

                await websocket.send_json({
                    "type": "done",
                    "hint_level": result.hint_level,
                    "programming_difficulty": result.programming_difficulty,
                    "maths_difficulty": result.maths_difficulty,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                })

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
