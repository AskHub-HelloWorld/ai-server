"""공통 cursor-based pagination 유틸리티."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar
from uuid import UUID

from sqlalchemy import Column, and_, or_
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

T = TypeVar("T")


@dataclass(frozen=True)
class PaginatedResult(Generic[T]):  # noqa: UP046
    """cursor 기반 페이지네이션 결과.

    ``next_cursor``가 None이면 마지막 페이지다.
    """

    items: Sequence[T]
    next_cursor: UUID | None
    has_more: bool


def paginate_query(
    db: Session,
    stmt: Select,
    *,
    model_class: type,
    cursor: UUID | None,
    limit: int,
    order_column: Column,
    id_column: Column,
    descending: bool = True,
) -> PaginatedResult:
    """cursor 기반 pagination을 적용하여 쿼리를 실행한다.

    Args:
        db: SQLAlchemy 세션.
        stmt: 기본 SELECT 쿼리 (WHERE 조건 적용 후).
        model_class: cursor 조회에 사용할 ORM 모델 클래스.
        cursor: 이전 페이지의 마지막 레코드 ID (없으면 첫 페이지).
        limit: 페이지 크기.
        order_column: 정렬 기준 컬럼 (created_at, updated_at 등).
        id_column: PK 컬럼 (tie-breaker).
        descending: True면 최신순 (DESC), False면 오래된순 (ASC).
    """
    if cursor is not None:
        cursor_obj = db.get(model_class, cursor)
        if cursor_obj is not None:
            cursor_order_val = getattr(cursor_obj, order_column.key)
            cursor_id_val = getattr(cursor_obj, id_column.key)
            if descending:
                stmt = stmt.where(
                    or_(
                        order_column < cursor_order_val,
                        and_(order_column == cursor_order_val, id_column < cursor_id_val),
                    )
                )
            else:
                stmt = stmt.where(
                    or_(
                        order_column > cursor_order_val,
                        and_(order_column == cursor_order_val, id_column > cursor_id_val),
                    )
                )

    if descending:
        stmt = stmt.order_by(order_column.desc(), id_column.desc())
    else:
        stmt = stmt.order_by(order_column.asc(), id_column.asc())

    stmt = stmt.limit(limit + 1)
    results = list(db.scalars(stmt).all())

    has_more = len(results) > limit
    items = results[:limit]
    next_cursor = getattr(items[-1], id_column.key) if has_more and items else None
    return PaginatedResult(items=items, next_cursor=next_cursor, has_more=has_more)
