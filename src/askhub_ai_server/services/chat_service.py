from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from askhub_ai_server.core.config import Settings
from askhub_ai_server.core.security import ServiceContext
from askhub_ai_server.models import ChatSession, Message
from askhub_ai_server.schemas.chat import (
    ChatRequest,
    HistoryMessage,
    SessionMessageRequest,
)
from askhub_ai_server.services.attachment_context import AttachmentContextBuilder
from askhub_ai_server.services.exceptions import ServiceError

logger = logging.getLogger(__name__)


class LLMClient(Protocol):
    def converse(self, request: ChatRequest) -> str: ...

    def converse_stream(self, request: ChatRequest) -> Iterable[str]: ...


class LLMRequestError(Exception):
    pass


@dataclass(frozen=True)
class PreparedChatMessage:
    session_id: UUID
    user_message_id: UUID
    chat_request: ChatRequest


@dataclass(frozen=True)
class CompletedChatMessage:
    session_id: UUID
    user_message_id: UUID
    assistant_message_id: UUID
    answer: str
    answerable: bool
    citations: list[dict]


class MessageRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def create_session(
        self,
        context: ServiceContext,
        title: str | None,
    ) -> ChatSession:
        session = ChatSession(user_id=context.user_id, team_id=context.team_id, title=title)
        self._db.add(session)
        self._db.commit()
        self._db.refresh(session)
        return session

    def list_sessions(
        self,
        context: ServiceContext,
        team_id: int | None = None,
    ) -> Sequence[ChatSession]:
        statement = select(ChatSession).where(ChatSession.user_id == context.user_id)
        if team_id is not None:
            statement = statement.where(ChatSession.team_id == team_id)
        elif context.team_id is not None:
            statement = statement.where(ChatSession.team_id == context.team_id)
        statement = statement.order_by(ChatSession.updated_at.desc(), ChatSession.created_at.desc())
        return self._db.scalars(statement).all()

    def get_session(self, session_id: UUID) -> ChatSession | None:
        return self._db.get(ChatSession, session_id)

    def list_messages(self, session_id: UUID) -> Sequence[Message]:
        statement = (
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.created_at.asc(), Message.id.asc())
        )
        return self._db.scalars(statement).all()

    def save_user_message(self, session: ChatSession, content: str) -> Message:
        message = Message(session_id=session.id, role="user", content=content)
        if session.title is None:
            session.title = _build_session_title(content)
        session.updated_at = datetime.now(UTC)
        self._db.add(message)
        self._db.commit()
        self._db.refresh(message)
        self._db.refresh(session)
        return message

    def save_assistant_message(
        self,
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
        session.updated_at = datetime.now(UTC)
        self._db.add(message)
        self._db.commit()
        self._db.refresh(message)
        return message

    def load_history(
        self,
        session_id: UUID,
        max_messages: int,
        exclude_message_id: UUID | None = None,
    ) -> list[HistoryMessage]:
        statement = select(Message).where(Message.session_id == session_id)
        if exclude_message_id is not None:
            statement = statement.where(Message.id != exclude_message_id)
        if max_messages > 0:
            statement = statement.order_by(Message.created_at.desc(), Message.id.desc()).limit(
                max_messages
            )
            messages = list(reversed(self._db.scalars(statement).all()))
        else:
            statement = statement.order_by(Message.created_at.asc(), Message.id.asc())
            messages = self._db.scalars(statement).all()

        return [HistoryMessage(role=message.role, content=message.content) for message in messages]


class ChatService:
    def __init__(
        self,
        db: Session,
        settings: Settings,
        llm: LLMClient,
        attachment_builder: AttachmentContextBuilder | None = None,
    ) -> None:
        self._settings = settings
        self._llm = llm
        self._repository = MessageRepository(db)
        self._attachment_builder = attachment_builder or AttachmentContextBuilder(db, settings)

    def create_session(self, context: ServiceContext, title: str | None) -> ChatSession:
        return self._repository.create_session(context, title)

    def list_sessions(
        self,
        context: ServiceContext,
        team_id: int | None = None,
    ) -> Sequence[ChatSession]:
        if team_id is not None and context.team_id != team_id:
            raise ServiceError(403, "team access denied")
        return self._repository.list_sessions(context, team_id)

    def get_session_detail(
        self,
        session_id: UUID,
        context: ServiceContext,
    ) -> tuple[ChatSession, Sequence[Message]]:
        session = self.require_session(session_id, context)
        return session, self._repository.list_messages(session.id)

    def prepare_message(
        self,
        session_id: UUID,
        request: SessionMessageRequest,
        context: ServiceContext,
    ) -> PreparedChatMessage:
        session = self.require_session(session_id, context)
        user_message = self._repository.save_user_message(session, request.message)
        history = self._repository.load_history(
            session.id,
            max_messages=self._settings.max_history_messages,
            exclude_message_id=user_message.id,
        )

        attachment_context = self._attachment_builder.build(request.file_ids, session)
        llm_message = (
            f"{attachment_context.text}\n\n{request.message}"
            if attachment_context.text
            else request.message
        )
        chat_request = ChatRequest(
            message=llm_message,
            user_id=session.user_id,
            team_id=session.team_id,
            session_id=str(session.id),
            history=history,
            attachments=attachment_context.attachments,
        )
        return PreparedChatMessage(
            session_id=session.id,
            user_message_id=user_message.id,
            chat_request=chat_request,
        )

    def create_message(
        self,
        session_id: UUID,
        request: SessionMessageRequest,
        context: ServiceContext,
    ) -> CompletedChatMessage:
        prepared = self.prepare_message(session_id, request, context)
        try:
            answer = self._llm.converse(prepared.chat_request)
        except Exception as exc:
            logger.exception("세션 메시지 LLM 호출 실패")
            raise LLMRequestError("LLM request failed") from exc

        return self.complete_message(
            session_id=prepared.session_id,
            user_message_id=prepared.user_message_id,
            context=context,
            answer=answer,
            answerable=True,
            citations=[],
        )

    def complete_message(
        self,
        session_id: UUID,
        user_message_id: UUID,
        context: ServiceContext,
        answer: str,
        answerable: bool,
        citations: list[dict],
    ) -> CompletedChatMessage:
        session = self.require_session(session_id, context)
        assistant_message = self._repository.save_assistant_message(
            session=session,
            content=answer,
            answerable=answerable,
            citations=citations,
        )
        return CompletedChatMessage(
            session_id=session.id,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message.id,
            answer=answer,
            answerable=answerable,
            citations=citations,
        )

    def require_session(self, session_id: UUID, context: ServiceContext) -> ChatSession:
        session = self._repository.get_session(session_id)
        if session is None:
            raise ServiceError(404, f"chat session not found: {session_id}")
        if session.user_id != context.user_id:
            raise ServiceError(404, "chat session not found")
        if context.team_id is not None and session.team_id != context.team_id:
            raise ServiceError(404, "chat session not found")
        return session


def _build_session_title(message: str) -> str:
    title = message.strip().replace("\n", " ")
    return title[:60] if title else "새 채팅"
