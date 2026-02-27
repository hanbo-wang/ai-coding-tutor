"""Stream metadata header parser tests."""

from app.services.stream_meta_parser import StreamMetaParser


def test_parses_header_and_body_across_chunks() -> None:
    parser = StreamMetaParser()
    out1 = parser.feed("<<GC_META_V1>>{\"same_problem\":true,")
    assert out1.meta_parsed is False
    assert out1.body_chunks == []

    out2 = parser.feed("\"is_elaboration\":false,\"programming_difficulty\":3,")
    assert out2.meta_parsed is False
    assert out2.body_chunks == []

    out3 = parser.feed("\"maths_difficulty\":2}<<END_GC_META>>Hello")
    assert out3.meta_parsed is True
    assert out3.meta is not None
    assert out3.meta["maths_difficulty"] == 2
    assert out3.body_chunks == ["Hello"]

    out4 = parser.feed(" world")
    assert out4.body_chunks == [" world"]


def test_invalid_json_drops_header_and_keeps_body() -> None:
    parser = StreamMetaParser()
    out = parser.feed("<<GC_META_V1>>{bad json}<<END_GC_META>>Visible text")
    assert out.meta_parsed is False
    assert out.parse_error_reason == "invalid_header_json"
    assert out.body_chunks == ["Visible text"]


def test_missing_header_falls_back_to_passthrough_after_limit() -> None:
    parser = StreamMetaParser(max_header_chars=20)
    payload = "Visible body without header. " * 12
    out = parser.feed(payload)
    assert out.parse_error_reason == "missing_header_marker"
    assert out.body_chunks == [payload]


def test_missing_header_short_reply_starts_streaming_before_finalize() -> None:
    """Short replies without a header should not be buffered until stream end."""
    parser = StreamMetaParser()

    out1 = parser.feed("Hello")
    assert out1.parse_error_reason == "missing_header_marker"
    assert out1.body_chunks == ["Hello"]

    out2 = parser.feed(" world")
    assert out2.body_chunks == [" world"]

    final = parser.finalize()
    assert final.body_chunks == []


def test_incomplete_header_is_dropped_on_finalize() -> None:
    parser = StreamMetaParser()
    parser.feed("<<GC_META_V1>>{\"same_problem\":true")
    out = parser.finalize()
    assert out.parse_error_reason == "incomplete_header"
    assert out.body_chunks == []
