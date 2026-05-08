"""Kiwi 기반 한국어 형태소 토크나이저 — BM25 검색 전처리."""

from __future__ import annotations

import logging
import re
import threading

logger = logging.getLogger(__name__)

# 검색에 유의미한 형태소 품사 태그 (Kiwi POS tags)
_SEARCH_POS_TAGS: set[str] = {
    "NNG",   # 일반 명사
    "NNP",   # 고유 명사
    "NNB",   # 의존 명사
    "NR",    # 수사
    "VV",    # 동사
    "VA",    # 형용사
    "SL",    # 영문
    "SN",    # 숫자
    "SH",    # 한자
}

# 영문/숫자/파일경로/함수명 등 비한국어 토큰 패턴 — 원형 보존
_NON_KOREAN_TOKEN_RE = re.compile(r"[a-zA-Z0-9_./\-]+")


class KoreanTokenizer:
    """Singleton Kiwi 기반 한국어 형태소 토크나이저.

    BM25 인덱싱/검색 전에 텍스트를 형태소 분석하여 명사, 동사 어간,
    영문 토큰 등을 추출한다. 교착어인 한국어에서 "검색합니다", "검색하는",
    "검색을"이 모두 동일한 "검색" 토큰으로 매칭되도록 한다.
    """

    _instance: KoreanTokenizer | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        from kiwipiepy import Kiwi

        self._kiwi = Kiwi()
        logger.info("Kiwi 한국어 형태소 분석기 초기화 완료")

    @classmethod
    def get_instance(cls) -> KoreanTokenizer:
        if cls._instance is not None:
            return cls._instance
        with cls._lock:
            if cls._instance is not None:
                return cls._instance
            cls._instance = cls()
            return cls._instance

    def tokenize_for_search(self, text: str) -> str:
        """텍스트에서 검색용 토큰을 추출하여 공백 결합 문자열로 반환한다.

        - 한국어: 명사/동사 어간/형용사 어간 추출
        - 영문/숫자/파일경로: 원형 보존
        - 실패 시 원문 반환
        """
        if not text or not text.strip():
            return text

        try:
            tokens: list[str] = []
            for token in self._kiwi.tokenize(text):
                if token.tag in _SEARCH_POS_TAGS:
                    form = token.form.strip()
                    if form:
                        tokens.append(form)

            if not tokens:
                return text

            return " ".join(tokens)
        except Exception:
            logger.debug("한국어 형태소 분석 실패 — 원문 반환", exc_info=True)
            return text


def tokenize_for_search(text: str) -> str:
    """모듈 레벨 편의 함수. Kiwi import 실패 시 원문 반환."""
    try:
        return KoreanTokenizer.get_instance().tokenize_for_search(text)
    except Exception:
        logger.debug("한국어 토크나이저 초기화 실패 — 원문 반환", exc_info=True)
        return text
