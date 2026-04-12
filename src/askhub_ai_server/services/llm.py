"""Bedrock LLM 서비스 — Converse API로 Amazon Nova Lite 호출."""

from __future__ import annotations

import logging
import re
from collections.abc import Generator

import boto3
from botocore.config import Config as BotoConfig

from askhub_ai_server.core.config import Settings, get_settings
from askhub_ai_server.schemas.chat import ChatAttachment, ChatRequest

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "당신은 AskHub의 사내 개발자 어시스턴트입니다.\n"
    "회사 개발자들의 기술 질문에 친절하고 정확하게 답변합니다.\n"
    "한국어로 답변하세요."
)

IMAGE_CONTENT_TYPE_TO_BEDROCK_FORMAT = {
    "image/png": "png",
    "image/jpeg": "jpeg",
    "image/jpg": "jpeg",
    "image/gif": "gif",
    "image/webp": "webp",
}

DOCUMENT_CONTENT_TYPE_TO_FORMAT = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "text/csv": "csv",
    "text/html": "html",
}

_DOCUMENT_NAME_RE = re.compile(r"[^a-zA-Z0-9\s\-\(\)\[\]]")


class BedrockLLMService:
    """boto3 bedrock-runtime 클라이언트를 사용한 LLM 호출."""

    def __init__(self, settings: Settings) -> None:
        self._model_id = settings.bedrock_model_id
        self._client = boto3.client(
            "bedrock-runtime",
            region_name=settings.aws_region,
            config=BotoConfig(
                retries={"max_attempts": 2, "mode": "adaptive"},
                read_timeout=60,
            ),
        )

    def _build_messages(self, request: ChatRequest) -> list[dict]:
        return build_converse_messages(request)

    def converse(self, request: ChatRequest) -> str:
        """Non-streaming 호출. 전체 응답 텍스트를 반환."""
        response = self._client.converse(
            modelId=self._model_id,
            messages=self._build_messages(request),
            system=[{"text": SYSTEM_PROMPT}],
        )
        return _extract_text_response(response)

    def converse_stream(self, request: ChatRequest) -> Generator[str, None, None]:
        """Streaming 호출. 토큰(텍스트 조각)을 하나씩 yield."""
        response = self._client.converse_stream(
            modelId=self._model_id,
            messages=self._build_messages(request),
            system=[{"text": SYSTEM_PROMPT}],
        )
        for event in response["stream"]:
            if "contentBlockDelta" in event:
                text = event["contentBlockDelta"]["delta"].get("text", "")
                if text:
                    yield text


def build_converse_messages(request: ChatRequest) -> list[dict]:
    messages: list[dict] = []
    for h in request.history:
        messages.append({"role": h.role, "content": [{"text": h.content}]})

    current_content: list[dict] = []
    for attachment in request.attachments:
        block = _build_image_content_block(attachment)
        if block is None:
            block = _build_document_content_block(attachment)
        if block is not None:
            current_content.append(block)
    current_content.append({"text": request.message})
    messages.append({"role": "user", "content": current_content})
    return messages


def _build_image_content_block(attachment: ChatAttachment) -> dict | None:
    image_format = IMAGE_CONTENT_TYPE_TO_BEDROCK_FORMAT.get(attachment.content_type)
    if image_format is None:
        return None
    return {
        "image": {
            "format": image_format,
            "source": {"bytes": attachment.data},
        }
    }


def _build_document_content_block(attachment: ChatAttachment) -> dict | None:
    doc_format = DOCUMENT_CONTENT_TYPE_TO_FORMAT.get(attachment.content_type)
    if doc_format is None:
        return None
    name = _DOCUMENT_NAME_RE.sub("", attachment.filename)[:100].strip() or "document"
    return {
        "document": {
            "format": doc_format,
            "name": name,
            "source": {"bytes": attachment.data},
        }
    }


def _extract_text_response(response: dict) -> str:
    content_blocks = response["output"]["message"].get("content", [])
    return "".join(block.get("text", "") for block in content_blocks)


# --- singleton ---

_service: BedrockLLMService | None = None


def get_llm_service() -> BedrockLLMService:
    global _service  # noqa: PLW0603
    if _service is not None:
        return _service

    settings = get_settings()
    _service = BedrockLLMService(settings)
    logger.info("Bedrock LLM 서비스 초기화 완료 (model=%s)", settings.bedrock_model_id)
    return _service
