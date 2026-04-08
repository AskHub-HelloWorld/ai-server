"""Bedrock LLM 서비스 — ConverseStream API로 Amazon Nova Micro 호출."""

from __future__ import annotations

import logging
import time
from collections.abc import Generator

import boto3
from botocore.config import Config as BotoConfig

from askhub_ai_server.core.config import Settings, get_settings
from askhub_ai_server.schemas.chat import ChatRequest

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "당신은 AskHub의 사내 개발자 어시스턴트입니다.\n"
    "회사 개발자들의 기술 질문에 친절하고 정확하게 답변합니다.\n"
    "한국어로 답변하세요."
)


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
        messages: list[dict] = []
        for h in request.history:
            messages.append({"role": h.role, "content": [{"text": h.content}]})
        messages.append({"role": "user", "content": [{"text": request.message}]})
        return messages

    def converse(self, request: ChatRequest) -> str:
        """Non-streaming 호출. 전체 응답 텍스트를 반환."""
        response = self._client.converse(
            modelId=self._model_id,
            messages=self._build_messages(request),
            system=[{"text": SYSTEM_PROMPT}],
        )
        return response["output"]["message"]["content"][0]["text"]

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


class MockLLMService:
    """Bedrock 미연결 시 사용하는 mock LLM. 토큰 단위로 시뮬레이션."""

    _MOCK_ANSWER = (
        "안녕하세요! AskHub AI 어시스턴트입니다. "
        "현재 Bedrock LLM이 연결되지 않아 mock 모드로 동작 중입니다. "
        "AWS 자격 증명을 설정하면 실제 AI 응답을 받을 수 있습니다."
    )

    def converse(self, request: ChatRequest) -> str:
        return self._MOCK_ANSWER

    def converse_stream(self, request: ChatRequest) -> Generator[str, None, None]:
        for word in self._MOCK_ANSWER.split(" "):
            yield word + " "
            time.sleep(0.05)


# --- singleton ---

_service: BedrockLLMService | MockLLMService | None = None


def get_llm_service() -> BedrockLLMService | MockLLMService:
    global _service  # noqa: PLW0603
    if _service is not None:
        return _service

    settings = get_settings()
    if settings.bedrock_available:
        try:
            _service = BedrockLLMService(settings)
            logger.info("Bedrock LLM 서비스 초기화 완료 (model=%s)", settings.bedrock_model_id)
        except Exception:
            logger.warning("Bedrock 클라이언트 생성 실패 — mock 모드로 전환", exc_info=True)
            _service = MockLLMService()
    else:
        logger.info("AWS_BEARER_TOKEN_BEDROCK 미설정 — mock 모드로 동작")
        _service = MockLLMService()
    return _service
