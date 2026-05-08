"""LLM 기반 쿼리 의도 분류 — RAG 파이프라인 조건부 실행."""

from __future__ import annotations

import logging
from collections.abc import Callable
from enum import StrEnum

logger = logging.getLogger(__name__)


class QueryIntent(StrEnum):
    """사용자 질문의 의도 분류."""

    RAG_NEEDED = "rag"
    GENERAL_CHAT = "chat"
    FOLLOW_UP = "followup"


class QueryRouter:
    """LLM을 사용하여 사용자 질문의 의도를 분류한다.

    - ``RAG_NEEDED``: 사내 문서/코드 검색이 필요한 기술 질문
    - ``GENERAL_CHAT``: 인사, 잡담 등 문서 검색이 불필요한 질문
    - ``FOLLOW_UP``: 이전 대화 맥락에 대한 후속 질문
    """

    def __init__(
        self,
        classify_fn: Callable[[str], str],
        *,
        enabled: bool = True,
    ) -> None:
        self._classify = classify_fn
        self._enabled = enabled

    def classify(self, query: str, *, has_history: bool = False) -> QueryIntent:
        """질문 의도를 분류한다. 실패 시 RAG_NEEDED로 fallback."""
        if not self._enabled:
            return QueryIntent.RAG_NEEDED

        try:
            result = self._classify(query).strip().lower()
            if result == "chat":
                logger.info("쿼리 라우팅: GENERAL_CHAT — %s", query[:60])
                return QueryIntent.GENERAL_CHAT
            if result == "followup" and has_history:
                logger.info("쿼리 라우팅: FOLLOW_UP — %s", query[:60])
                return QueryIntent.FOLLOW_UP
            logger.info("쿼리 라우팅: RAG_NEEDED — %s", query[:60])
            return QueryIntent.RAG_NEEDED
        except Exception:
            logger.warning("쿼리 라우팅 실패 — RAG_NEEDED로 fallback", exc_info=True)
            return QueryIntent.RAG_NEEDED
