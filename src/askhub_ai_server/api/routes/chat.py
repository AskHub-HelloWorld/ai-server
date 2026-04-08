"""세션 기반 AI 채팅 엔드포인트."""

import json
import logging
from collections.abc import Iterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from askhub_ai_server.core.database import SessionLocal, get_db
from askhub_ai_server.models import ChatSession, Message
from askhub_ai_server.models.file import UserFile
from askhub_ai_server.schemas.chat import (
    ChatRequest,
    ChatSessionCreateRequest,
    ChatSessionDetailResponse,
    ChatSessionListResponse,
    ChatSessionResponse,
    HistoryMessage,
    MessageResponse,
    SessionMessageRequest,
    SessionMessageResponse,
    SuggestedPost,
)
from askhub_ai_server.services.llm import get_llm_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

SSE_STREAM_DESCRIPTION = """\
**SSE 이벤트 형식:**

| event | data | 설명 |
|-------|------|------|
| `metadata` | `{"session_id": "...", "user_message_id": "..."}` | 세션/사용자 메시지 정보 |
| `token` | `{"delta": "텍스트 조각"}` | 토큰 단위 응답 |
| `done` | `{"assistant_message_id": "...", ...}` | 응답 저장 후 스트리밍 완료 |
| `error` | `{"message": "에러 내용"}` | 오류 발생 시 |
"""


def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post(
    "/sessions",
    response_model=ChatSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="채팅 세션 생성",
)
def create_chat_session(
    request: ChatSessionCreateRequest,
    db: Annotated[Session, Depends(get_db)],
) -> ChatSessionResponse:
    session = ChatSession(user_id=request.user_id, team_id=request.team_id, title=request.title)
    db.add(session)
    db.commit()
    db.refresh(session)
    return _session_response(session)


@router.get(
    "/sessions",
    response_model=ChatSessionListResponse,
    summary="채팅 세션 목록 조회",
)
def list_chat_sessions(
    user_id: int,
    db: Annotated[Session, Depends(get_db)],
    team_id: int | None = None,
) -> ChatSessionListResponse:
    statement = select(ChatSession).where(ChatSession.user_id == user_id)
    if team_id is not None:
        statement = statement.where(ChatSession.team_id == team_id)
    statement = statement.order_by(ChatSession.updated_at.desc(), ChatSession.created_at.desc())

    sessions = db.scalars(statement).all()
    return ChatSessionListResponse(sessions=[_session_response(session) for session in sessions])


@router.get(
    "/sessions/{session_id}",
    response_model=ChatSessionDetailResponse,
    summary="채팅 세션 상세 조회",
)
def get_chat_session(
    session_id: UUID,
    db: Annotated[Session, Depends(get_db)],
) -> ChatSessionDetailResponse:
    session = _get_session_or_404(db, session_id)
    messages = db.scalars(
        select(Message)
        .where(Message.session_id == session.id)
        .order_by(Message.created_at.asc(), Message.id.asc())
    ).all()
    return ChatSessionDetailResponse(
        **_session_response(session).model_dump(),
        messages=[_message_response(message) for message in messages],
    )


@router.post(
    "/sessions/{session_id}/messages",
    response_model=SessionMessageResponse,
    summary="세션에 메시지 전송 (non-streaming)",
)
def create_session_message(
    session_id: UUID,
    request: SessionMessageRequest,
    db: Annotated[Session, Depends(get_db)],
) -> SessionMessageResponse:
    session = _get_session_or_404(db, session_id)
    user_message = _save_user_message(db, session, request.message)
    history = _load_history(db, session.id, exclude_message_id=user_message.id)

    file_context = _load_file_context(db, request.file_ids)
    llm_message = f"{file_context}\n\n{request.message}" if file_context else request.message
    chat_request = _build_chat_request(session, llm_message, history)

    llm = get_llm_service()
    try:
        answer = llm.converse(chat_request)
        answerable = True
        suggested_post = None
    except Exception:
        logger.exception("세션 메시지 LLM 호출 실패")
        answer = "AI 응답 생성에 실패했습니다. 잠시 후 다시 시도해주세요."
        answerable = False
        suggested_post = _suggested_post(request.message)

    assistant_message = _save_assistant_message(
        db=db,
        session=session,
        content=answer,
        answerable=answerable,
        citations=[],
    )
    return SessionMessageResponse(
        session_id=session.id,
        user_message_id=user_message.id,
        assistant_message_id=assistant_message.id,
        answer=answer,
        answerable=answerable,
        citations=[],
        suggested_post=suggested_post,
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
    db: Annotated[Session, Depends(get_db)],
) -> StreamingResponse:
    session = _get_session_or_404(db, session_id)
    user_message = _save_user_message(db, session, request.message)
    history = _load_history(db, session.id, exclude_message_id=user_message.id)

    file_context = _load_file_context(db, request.file_ids)
    llm_message = f"{file_context}\n\n{request.message}" if file_context else request.message
    chat_request = _build_chat_request(session, llm_message, history)

    def event_stream() -> Iterator[str]:
        yield _sse(
            "metadata",
            {"session_id": str(session.id), "user_message_id": str(user_message.id)},
        )

        full_response = ""
        answerable = True
        try:
            for delta in get_llm_service().converse_stream(chat_request):
                full_response += delta
                yield _sse("token", {"delta": delta})
        except Exception:
            logger.exception("세션 메시지 LLM 스트리밍 실패")
            answerable = False
            full_response = "AI 응답 생성 중 오류가 발생했습니다."
            yield _sse("error", {"message": full_response})

        with SessionLocal() as streaming_db:
            streaming_session = _get_session_or_404(streaming_db, session.id)
            assistant_message = _save_assistant_message(
                db=streaming_db,
                session=streaming_session,
                content=full_response,
                answerable=answerable,
                citations=[],
            )

        yield _sse(
            "done",
            {
                "session_id": str(session.id),
                "user_message_id": str(user_message.id),
                "assistant_message_id": str(assistant_message.id),
                "full_response": full_response,
                "answerable": answerable,
            },
        )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _get_session_or_404(db: Session, session_id: UUID) -> ChatSession:
    session = db.get(ChatSession, session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"chat session not found: {session_id}",
        )
    return session


def _save_user_message(db: Session, session: ChatSession, content: str) -> Message:
    message = Message(session_id=session.id, role="user", content=content)
    if session.title is None:
        session.title = _build_session_title(content)
    db.add(message)
    db.commit()
    db.refresh(message)
    db.refresh(session)
    return message


def _save_assistant_message(
    db: Session,
    session: ChatSession,
    content: str,
    answerable: bool,
    citations: list[dict],
) -> Message:
    message = Message(
        session_id=session.id,
        role="assistant",
        content=content,
        answerable=answerable,
        citations=citations,
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def _load_history(
    db: Session,
    session_id: UUID,
    exclude_message_id: UUID | None = None,
) -> list[HistoryMessage]:
    statement = select(Message).where(Message.session_id == session_id)
    if exclude_message_id is not None:
        statement = statement.where(Message.id != exclude_message_id)
    statement = statement.order_by(Message.created_at.asc(), Message.id.asc())

    return [
        HistoryMessage(role=message.role, content=message.content)
        for message in db.scalars(statement).all()
    ]


def _build_chat_request(
    session: ChatSession,
    message: str,
    history: list[HistoryMessage],
) -> ChatRequest:
    return ChatRequest(
        message=message,
        user_id=session.user_id,
        team_id=session.team_id,
        session_id=str(session.id),
        history=history,
    )


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
    return MessageResponse(
        id=message.id,
        role=message.role,
        content=message.content,
        answerable=message.answerable,
        citations=message.citations or [],
        created_at=message.created_at,
    )


def _suggested_post(message: str) -> SuggestedPost:
    return SuggestedPost(
        title=f"AI가 답변하지 못한 질문: {message[:40]}",
        body=message,
        tags=["ai-fallback", "needs-human-answer"],
    )


def _build_session_title(message: str) -> str:
    title = message.strip().replace("\n", " ")
    return title[:60] if title else "새 채팅"


MAX_FILE_CONTENT_SIZE = 50 * 1024  # 50 KB per file


def _load_file_context(db: Session, file_ids: list[UUID]) -> str:
    """첨부 파일의 내용을 읽어 LLM context 문자열로 반환한다."""
    if not file_ids:
        return ""
    parts: list[str] = []
    for fid in file_ids:
        user_file = db.get(UserFile, fid)
        if user_file is None:
            logger.warning("첨부 파일을 찾을 수 없음: %s", fid)
            continue
        try:
            with open(user_file.storage_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(MAX_FILE_CONTENT_SIZE)
            parts.append(f"[첨부 파일: {user_file.filename}]\n{content}")
        except Exception:
            logger.warning("파일 읽기 실패: %s", user_file.storage_path)
    return "\n\n".join(parts)
