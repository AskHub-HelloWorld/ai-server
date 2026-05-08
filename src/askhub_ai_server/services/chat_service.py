from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from askhub_ai_server.core.config import Settings
from askhub_ai_server.core.security import ServiceContext
from askhub_ai_server.models import ChatSession, Message
from askhub_ai_server.models.enums import MessageRole, MessageStatus
from askhub_ai_server.schemas.chat import (
    ChatRequest,
    HistoryMessage,
    SessionMessageRequest,
)
from askhub_ai_server.services.attachment_context import AttachmentContextBuilder
from askhub_ai_server.services.citation_normalizer import normalize_inline_citations
from askhub_ai_server.services.exceptions import LLMRequestError, ServiceError
from askhub_ai_server.services.pagination import PaginatedResult, paginate_query
from askhub_ai_server.services.rag_context import RagContext, RagContextBuilder

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_RAG_USER_QUERY_TEMPLATE = (_PROMPTS_DIR / "rag_user_query.txt").read_text(
    encoding="utf-8",
).strip()


# ---------------------------------------------------------------------------
# Protocols / value objects
# ---------------------------------------------------------------------------

class LLMClient(Protocol):
    def converse(self, request: ChatRequest) -> str: ...

    def converse_stream(self, request: ChatRequest) -> Iterable[str]: ...

    def classify_query(self, query: str) -> str: ...

    def summarize_history(self, text: str) -> str: ...


@dataclass(frozen=True)
class PreparedChatMessage:
    """사용자 메시지 저장 후 LLM 호출 직전의 중간 상태.

    DB에는 user message(completed)와 assistant placeholder(pending)가 이미 저장되어 있다.
    ``chat_request``를 LLM에 전달하면 응답을 받아 assistant message를 완성할 수 있다.
    """

    session_id: UUID
    user_message_id: UUID
    assistant_message_id: UUID
    chat_request: ChatRequest
    rag_citations: list[dict] | None = None
    rag_answerable: bool = False

    def __post_init__(self) -> None:
        if self.rag_citations is None:
            object.__setattr__(self, "rag_citations", [])


@dataclass(frozen=True)
class CompletedChatMessage:
    """LLM 응답이 DB에 저장된 후의 최종 결과."""

    session_id: UUID
    user_message_id: UUID
    assistant_message_id: UUID
    answer: str
    answerable: bool
    citations: list[dict]


PaginatedSessions = PaginatedResult[ChatSession]
PaginatedMessages = PaginatedResult[Message]


# ---------------------------------------------------------------------------
# Repository — direct DB access
# ---------------------------------------------------------------------------

class MessageRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    # -- Session CRUD -------------------------------------------------------

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
        *,
        cursor: UUID | None = None,
        limit: int = 20,
    ) -> PaginatedSessions:
        stmt = select(ChatSession).where(ChatSession.user_id == context.user_id)
        if team_id is not None:
            stmt = stmt.where(ChatSession.team_id == team_id)
        elif context.team_id is not None:
            stmt = stmt.where(ChatSession.team_id == context.team_id)

        return paginate_query(
            self._db,
            stmt,
            model_class=ChatSession,
            cursor=cursor,
            limit=limit,
            order_column=ChatSession.updated_at,
            id_column=ChatSession.id,
            descending=True,
        )

    def get_session(self, session_id: UUID) -> ChatSession | None:
        return self._db.get(ChatSession, session_id)

    # -- Message CRUD -------------------------------------------------------

    def list_messages(
        self,
        session_id: UUID,
        *,
        cursor: UUID | None = None,
        limit: int = 50,
    ) -> PaginatedMessages:
        stmt = select(Message).where(Message.session_id == session_id)

        return paginate_query(
            self._db,
            stmt,
            model_class=Message,
            cursor=cursor,
            limit=limit,
            order_column=Message.created_at,
            id_column=Message.id,
            descending=False,
        )

    def save_user_message(self, session: ChatSession, content: str) -> Message:
        message = Message(
            session_id=session.id,
            role=MessageRole.USER,
            content=content,
            status=MessageStatus.COMPLETED,
        )
        if session.title is None:
            session.title = _build_session_title(content)
        session.updated_at = datetime.now(UTC)
        self._db.add(message)
        self._db.commit()
        self._db.refresh(message)
        self._db.refresh(session)
        return message

    def create_pending_assistant_message(self, session: ChatSession) -> Message:
        """Create a placeholder assistant message with status='pending'.

        This records the intent to generate an AI response *before* the LLM
        call starts, so failures are always visible in the database.
        """
        message = Message(
            session_id=session.id,
            role=MessageRole.ASSISTANT,
            content="",
            status=MessageStatus.PENDING,
        )
        self._db.add(message)
        self._db.commit()
        self._db.refresh(message)
        return message

    def complete_assistant_message(
        self,
        message_id: UUID,
        content: str,
        answerable: bool,
        citations: list[dict],
        rag_context_summary: str | None = None,
    ) -> Message:
        """Transition a pending assistant message to 'completed'."""
        message = self._db.get(Message, message_id)
        if message is None:
            raise ServiceError(404, f"assistant message not found: {message_id}")
        message.content = content
        message.status = MessageStatus.COMPLETED
        message.answerable = answerable
        message.citations = citations
        message.rag_context_summary = rag_context_summary

        session = self._db.get(ChatSession, message.session_id)
        if session is not None:
            session.updated_at = datetime.now(UTC)

        self._db.commit()
        self._db.refresh(message)
        return message

    def fail_assistant_message(self, message_id: UUID, reason: str) -> Message:
        """Transition a pending assistant message to 'failed'."""
        message = self._db.get(Message, message_id)
        if message is None:
            raise ServiceError(404, f"assistant message not found: {message_id}")
        message.status = MessageStatus.FAILED
        message.failure_reason = reason
        self._db.commit()
        self._db.refresh(message)
        return message

    def load_history(
        self,
        session_id: UUID,
        max_messages: int,
        exclude_message_id: UUID | None = None,
        *,
        include_rag_summary: bool = False,
    ) -> list[HistoryMessage]:
        stmt = select(Message).where(
            Message.session_id == session_id,
            Message.status == MessageStatus.COMPLETED,
        )
        if exclude_message_id is not None:
            stmt = stmt.where(Message.id != exclude_message_id)
        if max_messages > 0:
            stmt = stmt.order_by(Message.created_at.desc(), Message.id.desc()).limit(
                max_messages
            )
            messages = list(reversed(self._db.scalars(stmt).all()))
        else:
            stmt = stmt.order_by(Message.created_at.asc(), Message.id.asc())
            messages = list(self._db.scalars(stmt).all())

        history: list[HistoryMessage] = []
        for message in messages:
            content = message.content
            if (
                include_rag_summary
                and message.role == MessageRole.ASSISTANT
                and message.rag_context_summary
            ):
                content = f"{content}\n\n[이 답변에 사용된 참고자료: {message.rag_context_summary}]"
            history.append(HistoryMessage(role=message.role, content=content))
        return history


# ---------------------------------------------------------------------------
# Service — orchestration
# ---------------------------------------------------------------------------

class ChatService:
    def __init__(
        self,
        db: Session,
        settings: Settings,
        llm: LLMClient,
        attachment_builder: AttachmentContextBuilder | None = None,
        rag_builder: RagContextBuilder | None = None,
    ) -> None:
        self._settings = settings
        self._llm = llm
        self._repository = MessageRepository(db)
        self._attachment_builder = attachment_builder or AttachmentContextBuilder(db, settings)
        self._rag_builder = rag_builder

    # -- Session management -------------------------------------------------

    def create_session(self, context: ServiceContext, title: str | None) -> ChatSession:
        return self._repository.create_session(context, title)

    def list_sessions(
        self,
        context: ServiceContext,
        team_id: int | None = None,
        *,
        cursor: UUID | None = None,
        limit: int = 20,
    ) -> PaginatedSessions:
        if team_id is not None and context.team_id != team_id:
            raise ServiceError(403, "team access denied")
        return self._repository.list_sessions(context, team_id, cursor=cursor, limit=limit)

    def get_session_detail(
        self,
        session_id: UUID,
        context: ServiceContext,
        *,
        message_cursor: UUID | None = None,
        message_limit: int = 50,
    ) -> tuple[ChatSession, PaginatedMessages]:
        session = self.require_session(session_id, context)
        paginated = self._repository.list_messages(
            session.id, cursor=message_cursor, limit=message_limit,
        )
        return session, paginated

    # -- Message flow (pending → completed | failed) ------------------------

    def prepare_message(
        self,
        session_id: UUID,
        request: SessionMessageRequest,
        context: ServiceContext,
    ) -> PreparedChatMessage:
        """Save user message + pending assistant placeholder, build LLM request.

        After this call, the database contains:
          - user message   (status='completed')
          - assistant stub  (status='pending', content='')
        """
        session = self.require_session(session_id, context)
        user_message = self._repository.save_user_message(session, request.message)
        assistant_placeholder = self._repository.create_pending_assistant_message(session)

        # 히스토리 요약이 활성화되면 더 많은 메시지를 로드하여 요약 대상 확보
        max_msgs = self._settings.max_history_messages
        if self._settings.history_summarize_enabled:
            max_msgs = max(max_msgs, self._settings.history_summarize_threshold + self._settings.history_recent_count)

        history = self._repository.load_history(
            session.id,
            max_messages=max_msgs,
            exclude_message_id=user_message.id,
            include_rag_summary=self._settings.rag_context_preservation_enabled,
        )

        # 히스토리 요약 — 임계값 초과 시 오래된 메시지를 LLM으로 압축
        if self._settings.history_summarize_enabled:
            try:
                from askhub_ai_server.services.history_summarizer import HistorySummarizer

                summarizer = HistorySummarizer(self._llm.summarize_history)
                summary, history = summarizer.summarize_if_needed(
                    history,
                    max_recent=self._settings.history_recent_count,
                    threshold=self._settings.history_summarize_threshold,
                )
                if summary:
                    # Bedrock Converse API는 user/assistant 교대 필요
                    history = [
                        HistoryMessage(role="user", content=f"[이전 대화 요약]\n{summary}"),
                        HistoryMessage(role="assistant", content="네, 이전 대화 내용을 참고하겠습니다."),
                    ] + history
            except Exception:
                logger.warning("히스토리 요약 실패 — 원래 히스토리 유지", exc_info=True)

        attachment_context = self._attachment_builder.build(request.file_ids, session)

        # 쿼리 라우팅 — 의도 분류 후 RAG 조건부 실행
        rag_context = RagContext(text="", citations=[], chunks=[])
        if self._rag_builder is not None:
            should_search = True
            if self._settings.query_routing_enabled:
                try:
                    from askhub_ai_server.services.query_router import QueryIntent, QueryRouter

                    router = QueryRouter(self._llm.classify_query)
                    intent = router.classify(request.message, has_history=bool(history))
                    if intent == QueryIntent.GENERAL_CHAT:
                        should_search = False
                except Exception:
                    logger.warning("쿼리 라우팅 실패 — RAG 검색 진행", exc_info=True)

            if should_search:
                try:
                    rag_context = self._rag_builder.build(request.message, session.team_id)
                except Exception:
                    logger.warning("RAG 검색 실패 — RAG 없이 진행", exc_info=True)

        # LLM 메시지 구성: RAG context + attachment context + 사용자 질문
        context_parts: list[str] = []
        if rag_context.text:
            context_parts.append(rag_context.text)
        if attachment_context.text:
            context_parts.append(attachment_context.text)
        if rag_context.text:
            context_parts.append(_RAG_USER_QUERY_TEMPLATE.format(query=request.message))
        else:
            context_parts.append(request.message)
        llm_message = "\n\n".join(context_parts)

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
            assistant_message_id=assistant_placeholder.id,
            chat_request=chat_request,
            rag_citations=rag_context.citations,
            rag_answerable=rag_context.answerable,
        )

    def create_message(
        self,
        session_id: UUID,
        request: SessionMessageRequest,
        context: ServiceContext,
    ) -> CompletedChatMessage:
        """Non-streaming: prepare → LLM call → complete (or fail)."""
        prepared = self.prepare_message(session_id, request, context)
        try:
            answer = self._llm.converse(prepared.chat_request)
        except Exception as exc:
            logger.exception("세션 메시지 LLM 호출 실패")
            self._repository.fail_assistant_message(
                prepared.assistant_message_id, str(exc),
            )
            raise LLMRequestError(cause=str(exc)) from exc

        return self.complete_message(
            prepared=prepared,
            answer=answer,
            answerable=prepared.rag_answerable,
            citations=prepared.rag_citations,
        )

    def complete_message(
        self,
        prepared: PreparedChatMessage,
        answer: str,
        answerable: bool,
        citations: list[dict],
    ) -> CompletedChatMessage:
        """Transition pending assistant message → completed."""
        answer, citations = normalize_inline_citations(answer, citations)
        rag_summary = self._build_rag_context_summary(citations) if self._settings.rag_context_preservation_enabled else None
        self._repository.complete_assistant_message(
            prepared.assistant_message_id,
            content=answer,
            answerable=answerable,
            citations=citations,
            rag_context_summary=rag_summary,
        )
        return CompletedChatMessage(
            session_id=prepared.session_id,
            user_message_id=prepared.user_message_id,
            assistant_message_id=prepared.assistant_message_id,
            answer=answer,
            answerable=answerable,
            citations=citations,
        )

    # -- Helpers ------------------------------------------------------------

    @staticmethod
    def _build_rag_context_summary(citations: list[dict]) -> str | None:
        """Citation 목록에서 간결한 RAG 컨텍스트 요약을 생성한다 (LLM 호출 없음)."""
        if not citations:
            return None
        parts: list[str] = []
        for c in citations[:5]:
            title = c.get("path") or c.get("title", "")
            source_type = c.get("source_type", "")
            parts.append(f"- {title} ({source_type})")
        return "사용된 참고자료:\n" + "\n".join(parts)

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
