"""Model pricing metadata and helpers for runtime cost estimation."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any


# LLM pricing per million tokens (USD), used for estimates only.
# Values are documented in official pricing pages and may change.
LLM_MODEL_PRICING: dict[str, dict[str, dict[str, float]]] = {
    "google": {
        # Gemini 3 Flash Preview (Vertex AI)
        "gemini-3-flash-preview": {"input_per_mtok": 0.50, "output_per_mtok": 3.00},
        # Gemini 3.1 Pro Preview / Gemini 3 Pro Preview pricing bucket on Vertex AI page.
        "gemini-3.1-pro-preview": {"input_per_mtok": 2.00, "output_per_mtok": 12.00},
    },
    "anthropic": {
        "claude-sonnet-4-6": {"input_per_mtok": 3.00, "output_per_mtok": 15.00},
        "claude-haiku-4-5": {"input_per_mtok": 1.00, "output_per_mtok": 5.00},
    },
    "openai": {
        "gpt-5.2": {"input_per_mtok": 1.25, "output_per_mtok": 10.00},
        "gpt-5-mini": {"input_per_mtok": 0.25, "output_per_mtok": 2.00},
    },
}

# Backwards-compatible provider-level defaults (used as a fallback).
LLM_PRICING: dict[str, dict[str, float]] = {
    "anthropic": {"input_per_mtok": 3.00, "output_per_mtok": 15.00},
    "google": {"input_per_mtok": 0.50, "output_per_mtok": 3.00},
    "openai": {"input_per_mtok": 1.25, "output_per_mtok": 10.00},
}


def _round_usd(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def get_model_pricing(provider_id: str, model_id: str) -> dict[str, float]:
    provider = provider_id.lower()
    model = model_id.lower()
    by_provider = LLM_MODEL_PRICING.get(provider, {})
    pricing = by_provider.get(model)
    if pricing:
        return pricing
    return LLM_PRICING.get(provider, {"input_per_mtok": 0.0, "output_per_mtok": 0.0})


def _sum_modality_counts(details: Any) -> int | None:
    """Sum token counts from Vertex modality details if available."""
    if not isinstance(details, list):
        return None
    total = 0
    found = False
    for item in details:
        if not isinstance(item, dict):
            continue
        count = item.get("tokenCount")
        if isinstance(count, int):
            total += count
            found = True
    return total if found else None


def estimate_llm_cost_usd(
    provider_id: str,
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    usage_details: dict[str, Any] | None = None,
) -> float:
    """Estimate cost in USD from provider/model and token usage."""
    prompt_tokens = max(0, int(input_tokens or 0))
    completion_tokens = max(0, int(output_tokens or 0))

    # Vertex usage details can include per-modality token breakdowns. We still
    # charge with the same text rates for current app traffic, but prefer the
    # detailed counts when provided to reduce drift from summary fields.
    if isinstance(usage_details, dict):
        detailed_prompt = _sum_modality_counts(usage_details.get("promptTokensDetails"))
        detailed_completion = _sum_modality_counts(
            usage_details.get("candidatesTokensDetails")
        )
        if detailed_prompt is not None:
            prompt_tokens = detailed_prompt
        if detailed_completion is not None:
            completion_tokens = detailed_completion

    pricing = get_model_pricing(provider_id, model_id)
    input_cost = (Decimal(prompt_tokens) / Decimal(1_000_000)) * Decimal(
        str(pricing.get("input_per_mtok", 0.0))
    )
    output_cost = (Decimal(completion_tokens) / Decimal(1_000_000)) * Decimal(
        str(pricing.get("output_per_mtok", 0.0))
    )
    return _round_usd(input_cost + output_cost)
