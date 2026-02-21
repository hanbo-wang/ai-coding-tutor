"""Lazy initialisation of shared AI services (embedding and pedagogy engine)."""

from app.ai.embedding_service import EmbeddingService
from app.ai.llm_base import LLMProvider
from app.ai.pedagogy_engine import PedagogyEngine
from app.config import settings

_embedding_service: EmbeddingService | None = None
_pedagogy_engine: PedagogyEngine | None = None


async def get_ai_services(llm: LLMProvider) -> tuple[EmbeddingService, PedagogyEngine]:
    """Return the embedding service and pedagogy engine, initialising on first call."""
    global _embedding_service, _pedagogy_engine
    if _embedding_service is None:
        _embedding_service = EmbeddingService(
            provider=settings.embedding_provider,
            cohere_api_key=settings.cohere_api_key,
            voyage_api_key=settings.voyageai_api_key,
        )
        await _embedding_service.initialize()
    if _pedagogy_engine is None or _pedagogy_engine.llm is not llm:
        _pedagogy_engine = PedagogyEngine(_embedding_service, llm)
    return _embedding_service, _pedagogy_engine
