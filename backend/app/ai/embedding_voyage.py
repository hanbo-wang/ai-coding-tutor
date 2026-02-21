"""Voyage AI multimodal embedding provider.

Endpoint:
  POST https://api.voyageai.com/v1/multimodalembeddings

Request body:
  {
    "model": "voyage-multimodal-3.5",
    "inputs": [
      {"content": [{"type": "text", "text": "hello"}]}
    ]
  }

Response:
  {
    "data": [
      {"embedding": [0.013, -0.008, ...]}
    ],
    "usage": {"total_tokens": 2}
  }

Authentication:
  Bearer token via the VOYAGEAI_API_KEY environment variable.
"""

import logging
import base64
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

VOYAGE_API_URL = "https://api.voyageai.com/v1/multimodalembeddings"
VOYAGE_MODEL = "voyage-multimodal-3.5"


class VoyageEmbeddingService:
    """Embed text via the Voyage AI multimodal embeddings API."""

    def __init__(self, api_key: str):
        self.api_key = api_key
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
        """Embed a batch of texts in a single API call."""
        inputs = [
            {"content": [{"type": "text", "text": t}]}
            for t in texts
        ]
        payload = {
            "model": VOYAGE_MODEL,
            "inputs": inputs,
        }
        response = await self._client.post(VOYAGE_API_URL, json=payload)
        if response.status_code != 200:
            raise RuntimeError(
                f"Voyage AI error {response.status_code}: {response.text}"
            )
        data = response.json()
        return [item["embedding"] for item in data["data"]]

    async def embed_text(self, text: str) -> Optional[list[float]]:
        """Embed a single text string."""
        try:
            result = await self.embed_batch([text])
            return result[0] if result else None
        except Exception as e:
            logger.error("Voyage AI embedding failed: %s", e)
            return None

    async def embed_image(
        self, image_bytes: bytes, content_type: str
    ) -> Optional[list[float]]:
        """Embed an image via Voyage multimodal embeddings."""
        image_b64 = base64.b64encode(image_bytes).decode("ascii")
        payload_candidates = [
            {
                "model": VOYAGE_MODEL,
                "inputs": [
                    {
                        "content": [
                            {
                                "type": "image_base64",
                                "image_base64": image_b64,
                                "media_type": content_type,
                            }
                        ]
                    }
                ],
            },
            {
                "model": VOYAGE_MODEL,
                "inputs": [
                    {
                        "content": [
                            {
                                "type": "image",
                                "image": f"data:{content_type};base64,{image_b64}",
                            }
                        ]
                    }
                ],
            },
            {
                "model": VOYAGE_MODEL,
                "inputs": [
                    {
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": f"data:{content_type};base64,{image_b64}",
                            }
                        ]
                    }
                ],
            },
        ]

        for payload in payload_candidates:
            response = await self._client.post(VOYAGE_API_URL, json=payload)
            if response.status_code == 200:
                data = response.json()
                vectors = [item["embedding"] for item in data.get("data", [])]
                if vectors:
                    return vectors[0]

        logger.error("Voyage image embedding failed for content type %s", content_type)
        return None
