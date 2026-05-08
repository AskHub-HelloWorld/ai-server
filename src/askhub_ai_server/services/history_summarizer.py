"""대화 히스토리 요약 — 오래된 메시지를 LLM으로 압축."""

from __future__ import annotations

import logging
from collections.abc import Callable

from askhub_ai_server.schemas.chat import HistoryMessage

logger = logging.getLogger(__name__)


class HistorySummarizer:
    """대화 히스토리가 임계값을 초과하면 오래된 메시지를 요약한다.

    Bedrock Converse API는 user/assistant 역할 교대를 요구하므로,
    요약은 user/assistant 쌍으로 히스토리 앞에 삽입된다.
    """

    def __init__(
        self,
        summarize_fn: Callable[[str], str],
        *,
        enabled: bool = True,
    ) -> None:
        self._summarize = summarize_fn
        self._enabled = enabled

    def summarize_if_needed(
        self,
        history: list[HistoryMessage],
        *,
        max_recent: int = 10,
        threshold: int = 14,
    ) -> tuple[str | None, list[HistoryMessage]]:
        """히스토리가 threshold를 초과하면 오래된 부분을 요약한다.

        Returns:
            (summary_text_or_None, recent_messages)
        """
        if not self._enabled or len(history) <= threshold:
            return None, history

        older = history[:-max_recent]
        recent = history[-max_recent:]

        try:
            text = "\n".join(
                f"{m.role}: {m.content[:300]}" for m in older
            )
            summary = self._summarize(text)
            logger.info(
                "히스토리 요약 완료: older=%d messages, recent=%d messages",
                len(older),
                len(recent),
            )
            return summary, recent
        except Exception:
            logger.warning("히스토리 요약 실패 — 전체 히스토리 유지", exc_info=True)
            return None, history
