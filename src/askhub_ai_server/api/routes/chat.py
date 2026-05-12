"""세션 기반 AI 채팅 엔드포인트."""

import json
import logging
from collections.abc import Iterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from askhub_ai_server.core.config import Settings, get_settings
from askhub_ai_server.core.database import SessionLocal, get_db
from askhub_ai_server.core.security import ServiceContext, get_service_context
from askhub_ai_server.models import ChatSession, Message
from askhub_ai_server.models.enums import MessageRole, ResponseType
from askhub_ai_server.schemas.chat import (
    ChatSessionCreateRequest,
    ChatSessionDetailResponse,
    ChatSessionListResponse,
    ChatSessionResponse,
    MessageResponse,
    SessionMessageRequest,
    SessionMessageResponse,
)
from askhub_ai_server.services.chat_service import ChatService, MessageRepository
from askhub_ai_server.services.citation_normalizer import normalize_inline_citations
from askhub_ai_server.services.embedding import get_embedding_service
from askhub_ai_server.services.exceptions import LLMRequestError, ServiceError
from askhub_ai_server.services.llm import get_llm_service
from askhub_ai_server.services.rag_context import RagContextBuilder
from askhub_ai_server.services.retriever import PgVectorRetriever

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

SSE_STREAM_DESCRIPTION = """\
**SSE 이벤트 형식:**

| event | data | 설명 |
|-------|------|------|
| `metadata` | `{"session_id": "...", "user_message_id": "...", ...}` | 세션/메시지 정보 |
| `token` | `{"delta": "텍스트 조각"}` | 토큰 단위 응답 |
| `done` | `{"assistant_message_id": "...", ...}` | 응답 저장 후 스트리밍 완료 |
| `error` | `{"message": "에러 내용"}` | 오류 발생 시 (assistant message → failed) |
"""


def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _get_chat_service(
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ChatService:
    llm = get_llm_service()
    retriever = PgVectorRetriever(db, get_embedding_service(), settings)
    rag_builder = RagContextBuilder(
        retriever,
        max_context_tokens=settings.rag_max_context_tokens,
        query_rewriter=llm,
        answerable_threshold=settings.rag_answerable_threshold,
        settings=settings,
    )
    return ChatService(
        db=db, settings=settings, llm=llm, rag_builder=rag_builder,
    )


def _http_exception(error: ServiceError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=error.detail)


# ---------------------------------------------------------------------------
# Session CRUD
# ---------------------------------------------------------------------------


@router.post(
    "/sessions",
    response_model=ChatSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="채팅 세션 생성",
)
def create_chat_session(
    request: ChatSessionCreateRequest,
    context: Annotated[ServiceContext, Depends(get_service_context)],
    service: Annotated[ChatService, Depends(_get_chat_service)],
) -> ChatSessionResponse:
    return _session_response(service.create_session(context, request.title))


@router.get(
    "/sessions",
    response_model=ChatSessionListResponse,
    summary="채팅 세션 목록 조회",
)
def list_chat_sessions(
    context: Annotated[ServiceContext, Depends(get_service_context)],
    service: Annotated[ChatService, Depends(_get_chat_service)],
    settings: Annotated[Settings, Depends(get_settings)],
    team_id: int | None = None,
    cursor: Annotated[
        UUID | None,
        Query(description="이전 페이지 마지막 세션 ID"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100, description="페이지 크기")] = 20,
) -> ChatSessionListResponse:
    try:
        clamped_limit = min(limit, settings.max_page_limit)
        page = service.list_sessions(context, team_id, cursor=cursor, limit=clamped_limit)
    except ServiceError as exc:
        raise _http_exception(exc) from exc
    return ChatSessionListResponse(
        sessions=[_session_response(s) for s in page.items],
        next_cursor=str(page.next_cursor) if page.next_cursor else None,
        has_more=page.has_more,
    )


@router.get(
    "/sessions/{session_id}",
    response_model=ChatSessionDetailResponse,
    summary="채팅 세션 상세 조회",
)
def get_chat_session(
    session_id: UUID,
    context: Annotated[ServiceContext, Depends(get_service_context)],
    service: Annotated[ChatService, Depends(_get_chat_service)],
    settings: Annotated[Settings, Depends(get_settings)],
    message_cursor: Annotated[
        UUID | None,
        Query(description="메시지 커서"),
    ] = None,
    message_limit: Annotated[
        int,
        Query(ge=1, le=200, description="메시지 페이지 크기"),
    ] = 50,
) -> ChatSessionDetailResponse:
    try:
        clamped_limit = min(message_limit, settings.max_page_limit)
        session, msg_page = service.get_session_detail(
            session_id, context,
            message_cursor=message_cursor,
            message_limit=clamped_limit,
        )
    except ServiceError as exc:
        raise _http_exception(exc) from exc
    return ChatSessionDetailResponse(
        **_session_response(session).model_dump(),
        messages=[_message_response(m) for m in msg_page.items],
        next_message_cursor=str(msg_page.next_cursor) if msg_page.next_cursor else None,
        has_more_messages=msg_page.has_more,
    )


# ---------------------------------------------------------------------------
# Message send (non-streaming & streaming)
# ---------------------------------------------------------------------------


@router.post(
    "/sessions/{session_id}/messages",
    response_model=SessionMessageResponse,
    summary="세션에 메시지 전송 (non-streaming)",
)
def create_session_message(
    session_id: UUID,
    request: SessionMessageRequest,
    context: Annotated[ServiceContext, Depends(get_service_context)],
    service: Annotated[ChatService, Depends(_get_chat_service)],
) -> SessionMessageResponse:
    try:
        result = service.create_message(session_id, request, context)
    except ServiceError as exc:
        raise _http_exception(exc) from exc
    except LLMRequestError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.detail,
        ) from exc
    return SessionMessageResponse(
        session_id=result.session_id,
        user_message_id=result.user_message_id,
        assistant_message_id=result.assistant_message_id,
        answer=result.answer,
        answerable=result.answerable,
        citations=result.citations,
        suggested_post=None,
    )


@router.post(
    "/sessions/{session_id}/messages/stream",
    summary="세션에 메시지 전송 (SSE streaming)",
    description=(
        "세션에 사용자 메시지를 저장하고, AI 응답을 SSE로 스트리밍한 뒤 "
        "assistant 메시지를 저장합니다.\n\n"
    )
    + SSE_STREAM_DESCRIPTION,
    responses={
        200: {
            "content": {"text/event-stream": {}},
            "description": "SSE 스트리밍 응답",
        }
    },
)
def stream_session_message(
    session_id: UUID,
    request: SessionMessageRequest,
    context: Annotated[ServiceContext, Depends(get_service_context)],
    service: Annotated[ChatService, Depends(_get_chat_service)],
) -> StreamingResponse:
    try:
        prepared = service.prepare_message(session_id, request, context)
    except ServiceError as exc:
        raise _http_exception(exc) from exc

    def event_stream() -> Iterator[str]:
        # 1. metadata — client now knows all IDs up front
        yield _sse(
            "metadata",
            {
                "session_id": str(prepared.session_id),
                "user_message_id": str(prepared.user_message_id),
                "assistant_message_id": str(prepared.assistant_message_id),
            },
        )

        # 2. stream tokens from LLM
        full_response = ""
        try:
            for delta in get_llm_service().converse_stream(prepared.chat_request):
                full_response += delta
                yield _sse("token", {"delta": delta})
        except Exception as exc:
            logger.exception("세션 메시지 LLM 스트리밍 실패")
            # Mark assistant message as failed
            _fail_assistant_in_new_session(
                prepared.assistant_message_id, str(exc),
            )
            yield _sse("error", {"message": "LLM request failed"})
            return

        # 3. persist completed assistant message (separate DB session)
        citations = prepared.rag_citations or []
        full_response, citations = normalize_inline_citations(full_response, citations)
        answerable = bool(prepared.rag_answerable)
        rag_summary = ChatService._build_rag_context_summary(citations)
        try:
            _complete_assistant_in_new_session(
                prepared.assistant_message_id, full_response,
                citations=citations, answerable=answerable,
                rag_context_summary=rag_summary,
            )
        except Exception:
            logger.exception("세션 메시지 스트리밍 저장 실패")
            yield _sse("error", {"message": "message persistence failed"})
            return

        response_type = ResponseType.RAG if answerable and citations else ResponseType.GENERAL

        yield _sse(
            "done",
            {
                "session_id": str(prepared.session_id),
                "user_message_id": str(prepared.user_message_id),
                "assistant_message_id": str(prepared.assistant_message_id),
                "full_response": full_response,
                "answerable": answerable,
                "response_type": response_type,
                "citations": citations,
            },
        )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Streaming helpers — lightweight DB operations without full ChatService
# ---------------------------------------------------------------------------


def _complete_assistant_in_new_session(
    message_id: UUID,
    content: str,
    *,
    citations: list[dict] | None = None,
    answerable: bool = False,
    rag_context_summary: str | None = None,
) -> None:
    """Complete a pending assistant message using a fresh DB session."""
    with SessionLocal() as db:
        repo = MessageRepository(db)
        repo.complete_assistant_message(
            message_id, content, answerable=answerable, citations=citations or [],
            rag_context_summary=rag_context_summary,
        )


def _fail_assistant_in_new_session(message_id: UUID, reason: str) -> None:
    """Mark a pending assistant message as failed using a fresh DB session."""
    with SessionLocal() as db:
        repo = MessageRepository(db)
        repo.fail_assistant_message(message_id, reason)


# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------


def _session_response(session: ChatSession) -> ChatSessionResponse:
    return ChatSessionResponse(
        session_id=session.id,
        user_id=session.user_id,
        team_id=session.team_id,
        title=session.title,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def _message_response(message: Message) -> MessageResponse:
    citations = message.citations or []
    answerable = message.answerable
    response_type: str | None = None
    if message.role == MessageRole.ASSISTANT and answerable is not None:
        response_type = ResponseType.RAG if answerable and citations else ResponseType.GENERAL

    return MessageResponse(
        id=message.id,
        role=message.role,
        content=message.content,
        status=message.status,
        failure_reason=message.failure_reason,
        answerable=answerable,
        response_type=response_type,
        citations=citations,
        created_at=message.created_at,
    )
