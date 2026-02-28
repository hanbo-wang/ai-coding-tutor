"""LLM factory tests for provider/model selection and fallbacks."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.ai.llm_base import LLMError
from app.ai.llm_factory import get_llm_provider


class _FakeProvider:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs


def _settings(**overrides):
    base = dict(
        llm_provider="google",
        llm_model_google="gemini-3-flash-preview",
        google_gemini_transport="vertex",
        llm_model_anthropic="claude-sonnet-4-6",
        llm_model_openai="gpt-5.2",
        anthropic_api_key="",
        openai_api_key="",
        google_api_key="",
        google_application_credentials="",
        google_application_credentials_host_path="",
        google_cloud_project_id="",
        google_vertex_gemini_location="global",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_factory_builds_vertex_google_provider(monkeypatch) -> None:
    monkeypatch.setattr("app.ai.llm_factory.GoogleServiceAccountTokenProvider", lambda path: f"token:{path}")
    monkeypatch.setattr("app.ai.llm_factory.resolve_google_project_id", lambda path, pid: pid or "proj")
    monkeypatch.setattr("app.ai.llm_factory.GoogleGeminiProvider", _FakeProvider)

    provider = get_llm_provider(
        _settings(
            google_gemini_transport="vertex",
            google_api_key="AIza-present-but-not-selected",
            google_application_credentials="/tmp/sa.json",
            google_cloud_project_id="demo",
        )
    )

    assert isinstance(provider, _FakeProvider)
    assert provider.kwargs["project_id"] == "demo"
    assert provider.kwargs["model_id"] == "gemini-3-flash-preview"


def test_factory_normalises_vertex_location_for_global_only_models(monkeypatch) -> None:
    monkeypatch.setattr("app.ai.llm_factory.GoogleServiceAccountTokenProvider", lambda path: f"token:{path}")
    monkeypatch.setattr("app.ai.llm_factory.resolve_google_project_id", lambda path, pid: pid or "proj")
    monkeypatch.setattr("app.ai.llm_factory.GoogleGeminiProvider", _FakeProvider)

    provider = get_llm_provider(
        _settings(
            google_gemini_transport="vertex",
            google_application_credentials="/tmp/sa.json",
            google_cloud_project_id="demo",
            google_vertex_gemini_location="europe-west2",
            llm_model_google="gemini-3-flash-preview",
        )
    )

    assert isinstance(provider, _FakeProvider)
    assert provider.kwargs["location"] == "global"


def test_factory_uses_google_ai_studio_when_transport_selected(monkeypatch) -> None:
    monkeypatch.setattr("app.ai.llm_factory.GoogleGeminiAIStudioProvider", _FakeProvider)
    monkeypatch.setattr(
        "app.ai.llm_factory.GoogleServiceAccountTokenProvider",
        lambda path: (_ for _ in ()).throw(AssertionError("Vertex path should not be used")),
    )

    provider = get_llm_provider(
        _settings(
            google_gemini_transport="aistudio",
            google_api_key="AIza-test",
            google_application_credentials="/tmp/sa.json",
        )
    )

    assert isinstance(provider, _FakeProvider)
    assert provider.args[0] == "AIza-test"
    assert provider.kwargs["model_id"] == "gemini-3-flash-preview"


def test_factory_falls_back_to_openai_when_google_missing(monkeypatch) -> None:
    monkeypatch.setattr("app.ai.llm_factory.OpenAIProvider", _FakeProvider)

    provider = get_llm_provider(
        _settings(
            llm_provider="google",
            openai_api_key="sk-test",
            llm_model_openai="gpt-5-mini",
        )
    )

    assert isinstance(provider, _FakeProvider)
    assert provider.args[0] == "sk-test"
    assert provider.kwargs["model_id"] == "gpt-5-mini"


def test_factory_raises_when_nothing_configured() -> None:
    with pytest.raises(LLMError):
        get_llm_provider(_settings())
