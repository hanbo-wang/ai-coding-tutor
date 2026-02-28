"""Chat router helper tests."""

import asyncio
from types import SimpleNamespace

import pytest

from app.routers.chat import (
    GOOGLE_AI_STUDIO_PROVIDER,
    GOOGLE_VERTEX_PROVIDER,
    _build_enriched_message,
    _build_multimodal_user_parts,
    _build_notebook_context_block,
    _resolve_ws_token,
    _runtime_usage_provider_id,
    _split_uploads,
    _truncate_text_by_tokens,
    _user_facing_llm_error_message,
    _validate_upload_mix,
)


class FakeWebSocket:
    """Minimal WebSocket stub for token resolution tests."""

    def __init__(self, payload: str | Exception) -> None:
        self.payload = payload

    async def receive_text(self) -> str:
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class FakeLLM:
    """Simple token counter that uses word count."""

    def count_tokens(self, text: str) -> int:
        return len(text.split())


def _make_upload(
    file_type: str,
    *,
    filename: str = "file.txt",
    extracted_text: str | None = None,
    storage_path: str = "/tmp/missing",
    content_type: str = "text/plain",
):
    return SimpleNamespace(
        file_type=file_type,
        original_filename=filename,
        extracted_text=extracted_text,
        storage_path=storage_path,
        content_type=content_type,
    )


def test_split_uploads_separates_images_and_documents() -> None:
    """Image and document uploads should be separated into two lists."""
    image = _make_upload("image")
    document = _make_upload("document")
    images, documents = _split_uploads([image, document])
    assert images == [image]
    assert documents == [document]


def test_validate_upload_mix_returns_error_when_limits_exceeded(monkeypatch) -> None:
    """Too many attachments should return a user-facing error message."""
    monkeypatch.setattr("app.routers.chat.settings.upload_max_images_per_message", 1)
    monkeypatch.setattr("app.routers.chat.settings.upload_max_documents_per_message", 1)
    image_uploads = [_make_upload("image"), _make_upload("image")]
    document_uploads = [_make_upload("document"), _make_upload("document")]

    message = _validate_upload_mix(image_uploads, document_uploads)

    assert message is not None
    assert "up to 1 photos and 1 files" in message


def test_validate_upload_mix_accepts_payload_within_limits(monkeypatch) -> None:
    """Attachment sets within limits should not return an error."""
    monkeypatch.setattr("app.routers.chat.settings.upload_max_images_per_message", 2)
    monkeypatch.setattr("app.routers.chat.settings.upload_max_documents_per_message", 2)
    image_uploads = [_make_upload("image")]
    document_uploads = [_make_upload("document")]

    assert _validate_upload_mix(image_uploads, document_uploads) is None


def test_build_enriched_message_includes_document_text() -> None:
    """Document extracts should be appended to the user message."""
    document_uploads = [
        _make_upload(
            "document",
            filename="notes.txt",
            extracted_text="Key theorem details",
        )
    ]

    enriched = _build_enriched_message("Please explain this", document_uploads)

    assert "Please explain this" in enriched
    assert "[Attached document: notes.txt]" in enriched
    assert "Key theorem details" in enriched


def test_build_enriched_message_uses_attachment_only_fallback() -> None:
    """Attachment-only requests should return the default instruction."""
    document_uploads = [_make_upload("document", extracted_text=None)]
    enriched = _build_enriched_message("   ", document_uploads)
    assert enriched == "Please analyse the attached files."


def test_build_multimodal_user_parts_skips_missing_files(tmp_path) -> None:
    """Missing image files should be ignored from multimodal parts."""
    existing_image_path = tmp_path / "image.png"
    existing_image_path.write_bytes(b"binary-image-data")

    image_uploads = [
        _make_upload(
            "image",
            filename="a.png",
            storage_path=str(existing_image_path),
            content_type="image/png",
        ),
        _make_upload(
            "image",
            filename="b.png",
            storage_path=str(tmp_path / "missing.png"),
            content_type="image/png",
        ),
    ]

    parts = _build_multimodal_user_parts("Solve this", image_uploads)

    assert parts[0] == {"type": "text", "text": "Solve this"}
    assert len(parts) == 2
    assert parts[1]["type"] == "image"
    assert parts[1]["media_type"] == "image/png"
    assert parts[1]["data"]


def test_truncate_text_by_tokens_respects_budget() -> None:
    """Text should be shortened when token budget is exceeded."""
    llm = FakeLLM()
    text = "one two three four five"
    truncated = _truncate_text_by_tokens(llm, text, max_tokens=3)
    assert truncated == "one two three"


def test_build_notebook_context_block_includes_cell_and_error() -> None:
    """Notebook context block should include notebook, cell, and error sections."""
    llm = FakeLLM()
    block = _build_notebook_context_block(
        llm,
        extracted_text="line1 line2 line3 line4",
        cell_code="print('x')",
        error_output="Traceback line",
    )

    assert "--- Student's Notebook ---" in block
    assert "--- Current Cell ---" in block
    assert "print('x')" in block
    assert "--- Error Output ---" in block
    assert "Traceback line" in block


def test_runtime_usage_provider_id_maps_google_by_transport(monkeypatch) -> None:
    monkeypatch.setattr("app.routers.chat.settings.google_gemini_transport", "aistudio")
    assert _runtime_usage_provider_id("google") == GOOGLE_AI_STUDIO_PROVIDER

    monkeypatch.setattr("app.routers.chat.settings.google_gemini_transport", "vertex")
    assert _runtime_usage_provider_id("google") == GOOGLE_VERTEX_PROVIDER


def test_runtime_usage_provider_id_keeps_non_google_provider() -> None:
    assert _runtime_usage_provider_id("openai") == "openai"


def test_user_facing_llm_error_message_for_vertex_location_issue(monkeypatch) -> None:
    monkeypatch.setattr("app.routers.chat.settings.google_gemini_transport", "vertex")
    message = _user_facing_llm_error_message(
        Exception("Gemini API error 404: model not found in location"),
        "google",
    )
    assert "GOOGLE_VERTEX_GEMINI_LOCATION to 'global'" in message


def test_user_facing_llm_error_message_falls_back_to_generic() -> None:
    message = _user_facing_llm_error_message(Exception("timeout"), "openai")
    assert message == "AI service temporarily unavailable. Please try again."


@pytest.mark.asyncio
async def test_resolve_ws_token_prefers_query_token() -> None:
    """A query token should be used without reading a WebSocket frame."""
    websocket = FakeWebSocket(payload=asyncio.TimeoutError())
    token = await _resolve_ws_token(websocket, "query-token")
    assert token == "query-token"


@pytest.mark.asyncio
async def test_resolve_ws_token_reads_initial_auth_frame() -> None:
    """Auth frames should return a stripped token value."""
    websocket = FakeWebSocket('{"type":"auth","token":"  abc123  "}')
    token = await _resolve_ws_token(websocket, None)
    assert token == "abc123"


@pytest.mark.asyncio
async def test_resolve_ws_token_rejects_invalid_payload() -> None:
    """Invalid initial frames should be rejected."""
    websocket = FakeWebSocket('{"type":"message","token":"abc123"}')
    token = await _resolve_ws_token(websocket, None)
    assert token is None
