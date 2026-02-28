"""Lazy initialisation of shared AI services."""

from app.ai.llm_base import LLMProvider
from app.ai.pedagogy_engine import PedagogyEngine
_pedagogy_engine: PedagogyEngine | None = None


async def get_ai_services(llm: LLMProvider) -> PedagogyEngine:
    """Return a shared pedagogy engine bound to the active LLM instance."""
    global _pedagogy_engine
    if _pedagogy_engine is None or _pedagogy_engine.llm is not llm:
        _pedagogy_engine = PedagogyEngine(llm)
    return _pedagogy_engine
