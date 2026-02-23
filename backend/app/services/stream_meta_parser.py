"""Parse hidden metadata headers from a streamed LLM response."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal

from app.ai.prompts import GC_STREAM_META_END, GC_STREAM_META_START


ParserState = Literal["BUFFERING_HEADER", "STREAMING_BODY", "FALLBACK_PASSTHROUGH"]


@dataclass
class StreamMetaParserOutput:
    body_chunks: list[str] = field(default_factory=list)
    meta: dict | None = None
    meta_parsed: bool = False
    parse_error_reason: str | None = None


class StreamMetaParser:
    """Stateful parser for hidden metadata headers at the start of a stream."""

    def __init__(self, max_header_chars: int = 1024) -> None:
        self.max_header_chars = max(256, int(max_header_chars))
        self.state: ParserState = "BUFFERING_HEADER"
        self._buffer = ""
        self._parse_error_emitted = False

    def feed(self, chunk: str) -> StreamMetaParserOutput:
        output = StreamMetaParserOutput()
        if not chunk:
            return output

        if self.state in {"STREAMING_BODY", "FALLBACK_PASSTHROUGH"}:
            output.body_chunks.append(chunk)
            return output

        self._buffer += chunk
        return self._drain_buffer()

    def finalize(self) -> StreamMetaParserOutput:
        output = StreamMetaParserOutput()
        if self.state != "BUFFERING_HEADER" or not self._buffer:
            return output

        # No header marker at all: treat the buffered text as body.
        if GC_STREAM_META_START not in self._buffer:
            self.state = "FALLBACK_PASSTHROUGH"
            output.parse_error_reason = self._emit_error_reason("missing_header_marker")
            output.body_chunks.append(self._buffer)
            self._buffer = ""
            return output

        # Header started but never completed. Drop the buffer to avoid leaking metadata.
        self.state = "FALLBACK_PASSTHROUGH"
        output.parse_error_reason = self._emit_error_reason("incomplete_header")
        self._buffer = ""
        return output

    def _drain_buffer(self) -> StreamMetaParserOutput:
        output = StreamMetaParserOutput()

        if GC_STREAM_META_START not in self._buffer:
            if self._can_fallback_to_body_now():
                # The stream no longer matches a valid header prefix, so switch to
                # passthrough immediately instead of buffering until finalize().
                self.state = "FALLBACK_PASSTHROUGH"
                output.parse_error_reason = self._emit_error_reason("missing_header_marker")
                output.body_chunks.append(self._buffer)
                self._buffer = ""
                return output
            if len(self._buffer) > self.max_header_chars:
                self.state = "FALLBACK_PASSTHROUGH"
                output.parse_error_reason = self._emit_error_reason("missing_header_marker")
                output.body_chunks.append(self._buffer)
                self._buffer = ""
            return output

        start_index = self._buffer.find(GC_STREAM_META_START)
        prefix = self._buffer[:start_index]
        if prefix.strip():
            # Visible text before the marker means the model skipped the header protocol.
            self.state = "FALLBACK_PASSTHROUGH"
            output.parse_error_reason = self._emit_error_reason("body_before_header")
            output.body_chunks.append(self._buffer)
            self._buffer = ""
            return output

        end_index = self._buffer.find(GC_STREAM_META_END)
        if end_index < 0:
            if len(self._buffer) > self.max_header_chars:
                self.state = "FALLBACK_PASSTHROUGH"
                output.parse_error_reason = self._emit_error_reason("header_too_long")
                self._buffer = ""
            return output

        meta_start = start_index + len(GC_STREAM_META_START)
        raw_meta = self._buffer[meta_start:end_index].strip()
        body_start = end_index + len(GC_STREAM_META_END)
        body_tail = self._buffer[body_start:].lstrip("\r\n")
        self._buffer = ""
        self.state = "STREAMING_BODY"

        try:
            parsed = json.loads(raw_meta)
            if not isinstance(parsed, dict):
                raise ValueError("metadata header is not a JSON object")
            output.meta = parsed
            output.meta_parsed = True
        except Exception:
            output.parse_error_reason = self._emit_error_reason("invalid_header_json")

        if body_tail:
            output.body_chunks.append(body_tail)
        return output

    def _can_fallback_to_body_now(self) -> bool:
        """Return True when the buffered prefix can no longer become a valid header."""

        if not self._buffer:
            return False
        leading_ws = self._leading_whitespace_len(self._buffer)
        candidate = self._buffer[leading_ws:]
        if not candidate:
            return False
        return not GC_STREAM_META_START.startswith(candidate)

    @staticmethod
    def _leading_whitespace_len(text: str) -> int:
        idx = 0
        while idx < len(text) and text[idx].isspace():
            idx += 1
        return idx

    def _emit_error_reason(self, reason: str) -> str | None:
        if self._parse_error_emitted:
            return None
        self._parse_error_emitted = True
        return reason
