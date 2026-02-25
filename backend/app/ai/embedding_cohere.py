"""Cohere Embed v4 text embedding provider.

Endpoint:
  POST https://api.cohere.com/v2/embed

Request body:
  {
    "model": "embed-v4.0",
    "input_type": "search_query",
    "texts": ["hello"],
    "embedding_types": ["float"]
  }

Response:
  {
    "id": "...",
    "embeddings": {
      "float": [[0.013, -0.008, ...]]
    },
    "texts": ["hello"],
    "meta": {"api_version": {"version": "2"}}
  }

Authentication:
  Bearer token via the COHERE_API_KEY environment variable.
"""

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

COHERE_API_URL = "https://api.cohere.com/v2/embed"


class CohereEmbeddingService:
    """Embed text via the Cohere Embed v4 API."""

    def __init__(self, api_key: str, model_id: str):
        self.api_key = api_key
        self.model_id = model_id
        self._client = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts in a single API call (max 96 per call)."""
        payload = {
            "model": self.model_id,
            "input_type": "search_query",
            "texts": texts,
            "embedding_types": ["float"],
            "output_dimension": 256,
        }
        response = await self._client.post(COHERE_API_URL, json=payload)
        if response.status_code != 200:
            raise RuntimeError(
                f"Cohere embed error {response.status_code}: {response.text}"
            )
        data = response.json()
        return data["embeddings"]["float"]

    async def embed_text(self, text: str) -> Optional[list[float]]:
        """Embed a single text string."""
        try:
            result = await self.embed_batch([text])
            return result[0] if result else None
        except Exception as e:
            logger.error("Cohere embedding failed: %s", e)
            return None

