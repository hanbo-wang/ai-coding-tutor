"""Vertex AI multimodal embedding provider (`multimodalembedding@001`)."""

from __future__ import annotations

import base64
import logging
from typing import Optional

import httpx

from app.ai.google_auth import GoogleServiceAccountTokenProvider

logger = logging.getLogger(__name__)


class VertexEmbeddingService:
    """Embed text and images via Vertex AI multimodal embeddings."""

    def __init__(
        self,
        token_provider: GoogleServiceAccountTokenProvider,
        project_id: str,
        location: str,
        model_id: str = "multimodalembedding@001",
        dimension: int = 256,
    ) -> None:
        self._token_provider = token_provider
        self._project_id = project_id
        self._location = location
        self.model_id = model_id
        self.dimension = dimension
        # `multimodalembedding@001` predict may reject multiple instances in one call.
        self._max_batch_instances = 1
        self._client = httpx.AsyncClient(
            timeout=30.0,
            headers={"Content-Type": "application/json"},
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )

    def _predict_url(self) -> str:
        return (
            f"https://{self._location}-aiplatform.googleapis.com/v1/"
            f"projects/{self._project_id}/locations/{self._location}/publishers/google/"
            f"models/{self.model_id}:predict"
        )

    async def close(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _extract_embedding(prediction: dict) -> list[float] | None:
        for key in ("textEmbedding", "imageEmbedding", "embedding"):
            value = prediction.get(key)
            if isinstance(value, list) and value:
                try:
                    return [float(item) for item in value]
                except (TypeError, ValueError):
                    continue
        # Some responses nest the vector.
        embeddings = prediction.get("embeddings")
        if isinstance(embeddings, dict):
            for key in ("textEmbedding", "imageEmbedding"):
                value = embeddings.get(key)
                if isinstance(value, list) and value:
                    try:
                        return [float(item) for item in value]
                    except (TypeError, ValueError):
                        continue
        return None

    async def _predict(self, instances: list[dict]) -> list[list[float]]:
        token = await self._token_provider.get_access_token()
        payload = {
            "instances": instances,
            "parameters": {"dimension": self.dimension},
        }
        response = await self._client.post(
            self._predict_url(),
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code != 200:
            raise RuntimeError(f"Vertex embedding error {response.status_code}: {response.text}")
        data = response.json()
        predictions = data.get("predictions", [])
        vectors: list[list[float]] = []
        for pred in predictions:
            if not isinstance(pred, dict):
                continue
            embedding = self._extract_embedding(pred)
            if embedding:
                vectors.append(embedding)
        if len(vectors) != len(instances):
            raise RuntimeError(
                f"Vertex embedding returned {len(vectors)} vectors for {len(instances)} inputs"
            )
        return vectors

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors: list[list[float]] = []
        for i in range(0, len(texts), self._max_batch_instances):
            chunk = texts[i : i + self._max_batch_instances]
            instances = [{"text": text} for text in chunk]
            vectors.extend(await self._predict(instances))
        return vectors

    async def embed_text(self, text: str) -> Optional[list[float]]:
        try:
            result = await self.embed_batch([text])
            return result[0] if result else None
        except Exception as exc:
            logger.error("Vertex embedding failed: %s", exc)
            return None

    async def embed_image(
        self,
        image_bytes: bytes,
        content_type: str,
    ) -> Optional[list[float]]:
        try:
            image_b64 = base64.b64encode(image_bytes).decode("ascii")
            result = await self._predict(
                [{"image": {"bytesBase64Encoded": image_b64}}]
            )
            return result[0] if result else None
        except Exception as exc:
            logger.error("Vertex image embedding failed: %s", exc)
            return None
