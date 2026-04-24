"""Stale pending message cleanup — 비정상 종료로 남은 pending 메시지를 failed 처리."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.orm import Session

from askhub_ai_server.models import Message
from askhub_ai_server.models.enums import MessageStatus

logger = logging.getLogger(__name__)


def cleanup_stale_pending_messages(db: Session, *, max_age_minutes: int = 10) -> int:
    """``pending`` 상태로 *max_age_minutes* 이상 경과한 메시지를 ``failed`` 처리한다.

    서버 재시작 시 호출하여, 이전 프로세스 크래시로 남은 좀비 메시지를 정리한다.
    """
    cutoff = datetime.now(UTC) - timedelta(minutes=max_age_minutes)
    stmt = (
        update(Message)
        .where(Message.status == MessageStatus.PENDING, Message.created_at < cutoff)
        .values(status=MessageStatus.FAILED, failure_reason="Timed out (stale pending cleanup)")
    )
    result = db.execute(stmt)
    db.commit()
    count = result.rowcount
    if count:
        logger.info("Stale pending 메시지 %d건 failed 처리 완료", count)
    return count
