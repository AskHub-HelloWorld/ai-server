"""Bedrock LLM 서비스 — Converse API로 Amazon Nova Lite 호출."""

from __future__ import annotations

import logging
import re
from collections.abc import Generator
from pathlib import Path

import boto3
from botocore.config import Config as BotoConfig

from askhub_ai_server.core.config import Settings, get_settings
from askhub_ai_server.schemas.chat import ChatAttachment, ChatRequest
from askhub_ai_server.services.circuit_breaker import CircuitBreaker, circuit_protected

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def _load_prompt(name: str) -> str:
    """prompts/ 디렉토리에서 텍스트 파일을 읽어 반환한다."""
    return (_PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8").strip()


SYSTEM_PROMPT = _load_prompt("system")
QUERY_REWRITE_SYSTEM_PROMPT = _load_prompt("query_rewrite")
SUMMARIZE_SYSTEM_PROMPT = _load_prompt("summarize")
CODEBASE_SUMMARIZE_SYSTEM_PROMPT = _load_prompt("codebase_summarize")

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
_QUERY_LABEL_RE = re.compile(
    r"^\s*(?:검색\s*질의|검색어|질의|query|keywords?)\s*[:：]\s*",
    re.IGNORECASE,
)
_QUERY_BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")
_QUERY_STOPWORDS = {
    "검색",
    "검색어",
    "질의",
    "질문",
    "답변",
    "설명",
    "설명해라",
    "알려줘",
    "알려주세요",
    "무엇인가",
    "무엇인가요",
    "무엇인지",
}


class BedrockLLMService:
    """boto3 bedrock-runtime 클라이언트를 사용한 LLM 호출."""

    def __init__(self, settings: Settings) -> None:
        self._model_id = settings.bedrock_model_id
        self._client = boto3.client(
            "bedrock-runtime",
            region_name=settings.aws_region,
            config=BotoConfig(
                retries={"max_attempts": 2, "mode": "adaptive"},
                read_timeout=settings.llm_timeout_seconds,
            ),
        )
        self._circuit = CircuitBreaker(
            failure_threshold=settings.llm_circuit_failure_threshold,
            recovery_timeout=settings.llm_circuit_recovery_seconds,
            name="bedrock-llm",
        )

    @property
    def circuit_metrics(self) -> dict:
        return self._circuit.metrics

    def _build_messages(self, request: ChatRequest) -> list[dict]:
        return build_converse_messages(request)

    def converse(self, request: ChatRequest) -> str:
        """Non-streaming 호출. 전체 응답 텍스트를 반환."""
        with circuit_protected(self._circuit, "converse", self._model_id):
            response = self._client.converse(
                modelId=self._model_id,
                messages=self._build_messages(request),
                system=[{"text": SYSTEM_PROMPT}],
            )
            return _extract_text_response(response)

    def rewrite_for_retrieval(self, query: str) -> str:
        """사용자 질문을 RAG 검색에 적합한 질의로 변환한다."""
        with circuit_protected(self._circuit, "rewrite_for_retrieval", self._model_id):
            response = self._client.converse(
                modelId=self._model_id,
                messages=[{"role": "user", "content": [{"text": query}]}],
                system=[{"text": QUERY_REWRITE_SYSTEM_PROMPT}],
                inferenceConfig={"maxTokens": 120, "temperature": 0.0},
            )
            return _sanitize_retrieval_query(_extract_text_response(response)) or query

    def summarize(self, text: str) -> str:
        """텍스트를 3~5문장으로 요약한다."""
        with circuit_protected(self._circuit, "summarize", self._model_id):
            response = self._client.converse(
                modelId=self._model_id,
                messages=[{"role": "user", "content": [{"text": text}]}],
                system=[{"text": SUMMARIZE_SYSTEM_PROMPT}],
                inferenceConfig={"maxTokens": 500, "temperature": 0.3},
            )
            return _extract_text_response(response)

    def summarize_codebase(self, text: str) -> str:
        """코드베이스 구조 + 샘플 코드를 바탕으로 프로젝트를 요약한다."""
        with circuit_protected(self._circuit, "summarize_codebase", self._model_id):
            response = self._client.converse(
                modelId=self._model_id,
                messages=[{"role": "user", "content": [{"text": text}]}],
                system=[{"text": CODEBASE_SUMMARIZE_SYSTEM_PROMPT}],
                inferenceConfig={"maxTokens": 500, "temperature": 0.3},
            )
            return _extract_text_response(response)

    def converse_stream(self, request: ChatRequest) -> Generator[str, None, None]:
        """Streaming 호출. 토큰(텍스트 조각)을 하나씩 yield."""
        with circuit_protected(self._circuit, "stream", self._model_id):
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


def _sanitize_retrieval_query(query: str) -> str:
    cleaned_parts: list[str] = []
    for raw_part in re.split(r"[\n,;|]+", query):
        part = _QUERY_LABEL_RE.sub("", raw_part)
        part = _QUERY_BULLET_RE.sub("", part)
        part = part.replace("`", " ").replace('"', " ").replace("'", " ")
        part = " ".join(part.split())
        if part:
            cleaned_parts.append(part)

    tokens: list[str] = []
    for token in " ".join(cleaned_parts).split():
        normalized = token.strip()
        if not normalized:
            continue
        if normalized.casefold() in _QUERY_STOPWORDS:
            continue
        tokens.append(normalized)
        if len(tokens) >= 16:
            break

    return " ".join(tokens)[:180].strip()


# --- singleton ---

_service: BedrockLLMService | None = None
_service_lock = __import__("threading").Lock()


def get_llm_service() -> BedrockLLMService:
    global _service  # noqa: PLW0603
    if _service is not None:
        return _service

    with _service_lock:
        if _service is not None:
            return _service
        settings = get_settings()
        _service = BedrockLLMService(settings)
        logger.info("Bedrock LLM 서비스 초기화 완료 (model=%s)", settings.bedrock_model_id)
        return _service
