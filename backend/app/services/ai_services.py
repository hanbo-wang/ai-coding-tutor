"""Lazy initialisation of shared AI services (optional embedding + pedagogy engine)."""

import logging

from app.ai.embedding_service import EmbeddingService
from app.ai.llm_base import LLMProvider
from app.ai.pedagogy_engine import PedagogyEngine
from app.config import settings

logger = logging.getLogger(__name__)

_embedding_service: EmbeddingService | None = None
_pedagogy_engine: PedagogyEngine | None = None


async def get_ai_services(llm: LLMProvider) -> tuple[EmbeddingService | None, PedagogyEngine]:
    """Return shared AI services, allowing chat to run without embeddings by default."""
    global _embedding_service, _pedagogy_engine
    embedding_filters_enabled = bool(
        settings.chat_enable_greeting_filter or settings.chat_enable_off_topic_filter
    )
    if embedding_filters_enabled and _embedding_service is None:
        try:
            _embedding_service = EmbeddingService(
                provider=settings.embedding_provider,
                google_application_credentials=settings.google_application_credentials,
                google_application_credentials_host_path=settings.google_application_credentials_host_path,
                google_cloud_project_id=settings.google_cloud_project_id,
                vertex_location=settings.google_vertex_embedding_location,
                cohere_model_id=settings.embedding_model_cohere,
                vertex_model_id=settings.embedding_model_vertex,
                voyage_model_id=settings.embedding_model_voyage,
                cohere_api_key=settings.cohere_api_key,
                voyage_api_key=settings.voyageai_api_key,
            )
            await _embedding_service.initialize()
        except Exception as exc:
            logger.warning(
                "Embedding service unavailable; greeting/off-topic filters will be skipped: %s",
                exc,
            )
            _embedding_service = None
    if (
        _pedagogy_engine is None
        or _pedagogy_engine.llm is not llm
        or _pedagogy_engine.embedding_service is not _embedding_service
    ):
        _pedagogy_engine = PedagogyEngine(
            _embedding_service,
            llm,
        )
    return _embedding_service, _pedagogy_engine
