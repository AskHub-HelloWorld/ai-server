"""Bedrock Titan Embed v2 서비스 — 텍스트 → 벡터 임베딩 생성."""

from __future__ import annotations

import json
import logging
import time

import boto3
from botocore.config import Config as BotoConfig

from askhub_ai_server.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

# Titan Embed v2 input limit
_MAX_INPUT_TOKENS = 8192


class BedrockEmbeddingService:
    """Amazon Bedrock Titan Embed v2로 텍스트 임베딩을 생성한다."""

    def __init__(self, settings: Settings) -> None:
        self._model_id = settings.bedrock_embed_model_id
        self._dimensions = settings.rag_embedding_dimensions
        self._client = boto3.client(
            "bedrock-runtime",
            region_name=settings.aws_region,
            config=BotoConfig(
                retries={"max_attempts": 3, "mode": "adaptive"},
                read_timeout=30,
            ),
        )

    def embed_text(self, text: str) -> list[float]:
        """단일 텍스트를 임베딩 벡터로 변환한다."""
        start = time.monotonic()
        response = self._client.invoke_model(
            modelId=self._model_id,
            contentType="application/json",
            body=json.dumps({
                "inputText": text,
                "dimensions": self._dimensions,
                "normalize": True,
            }),
        )
        result = json.loads(response["body"].read())
        duration_ms = round((time.monotonic() - start) * 1000)
        logger.debug(
            "Embedding generated",
            extra={"model": self._model_id, "duration_ms": duration_ms},
        )
        return result["embedding"]

    def embed_batch(self, texts: list[str], batch_size: int = 20) -> list[list[float]]:
        """여러 텍스트를 순차적으로 임베딩한다.

        Titan Embed v2는 네이티브 배치 API를 제공하지 않으므로
        rate-limit을 고려하여 순차 호출한다.
        """
        results: list[list[float]] = []
        total = len(texts)
        for i, text in enumerate(texts):
            results.append(self.embed_text(text))
            if (i + 1) % batch_size == 0:
                logger.info("Embedding progress: %d/%d", i + 1, total)
        return results


# --- singleton ---

_service: BedrockEmbeddingService | None = None
_service_lock = __import__("threading").Lock()


def get_embedding_service() -> BedrockEmbeddingService:
    global _service  # noqa: PLW0603
    if _service is not None:
        return _service

    with _service_lock:
        if _service is not None:
            return _service
        settings = get_settings()
        _service = BedrockEmbeddingService(settings)
        logger.info(
            "Bedrock Embedding 서비스 초기화 완료 (model=%s, dim=%d)",
            settings.bedrock_embed_model_id,
            settings.rag_embedding_dimensions,
        )
        return _service
