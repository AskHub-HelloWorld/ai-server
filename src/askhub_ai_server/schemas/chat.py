from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class HistoryMessage(BaseModel):
    """LLM 호출에 전달하는 이전 대화 메시지."""

    model_config = ConfigDict(
        json_schema_extra={"example": {"role": "user", "content": "안녕하세요"}}
    )

    role: Literal["user", "assistant"] = Field(description="메시지 역할")
    content: str = Field(description="메시지 내용")


class ChatAttachment(BaseModel):
    """LLM 호출에 전달할 채팅 첨부 파일."""

    filename: str = Field(description="사용자가 업로드한 원본 파일명")
    content_type: str = Field(description="정규화된 MIME content type")
    data: bytes = Field(description="첨부 파일 bytes")


class ChatRequest(BaseModel):
    """세션 API가 LLM 서비스로 전달하는 내부 채팅 요청."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "message": "배포 파이프라인은 어디에 있나요?",
                "user_id": 1,
                "team_id": 10,
                "session_id": "sess-abc123",
                "history": [
                    {"role": "user", "content": "안녕하세요"},
                    {"role": "assistant", "content": "안녕하세요! 무엇을 도와드릴까요?"},
                ],
            }
        }
    )

    message: str = Field(min_length=1, description="사용자의 현재 질문")
    user_id: int | None = Field(default=None, description="사용자 ID (Backend User 테이블)")
    team_id: int | None = Field(default=None, description="팀 ID (Backend Team 테이블)")
    session_id: str | None = Field(default=None, description="대화 세션 식별자")
    history: list[HistoryMessage] = Field(
        default_factory=list,
        description="ai-server가 ai.messages 테이블에서 조회한 이전 대화 히스토리",
    )
    attachments: list[ChatAttachment] = Field(
        default_factory=list,
        description="현재 사용자 메시지에 첨부된 LLM 입력 파일",
    )


class Citation(BaseModel):
    """답변 근거 출처 — 인라인 인용 [N]과 매핑."""

    index: int = Field(description="인라인 인용 번호 (1-based, LLM 응답의 [N]과 매핑)")
    title: str
    source_type: str
    url: str | None = None
    is_external: bool = Field(
        default=False,
        description="True이면 url이 외부 링크(예: GitHub), False이면 내부 API 경로",
    )
    viewer_type: str | None = Field(
        default=None,
        description="문서 뷰어 유형: 'pdf', 'text', 'external'",
    )
    repo: str | None = None
    file_id: str | None = None
    path: str | None = None
    chunk_index: int | None = None
    commit_sha: str | None = None
    line_start: int | None = None
    line_end: int | None = None


class SuggestedPost(BaseModel):
    """AI가 답변 불가 시 커뮤니티 게시글 초안 (Phase 3 예정)."""

    title: str
    body: str
    tags: list[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    """AI 채팅 응답 (non-streaming)."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "answer": "배포 파이프라인은 .github/workflows/deploy.yml에 정의되어 있습니다.",
                "answerable": True,
                "citations": [],
                "suggested_post": None,
            }
        }
    )

    answer: str = Field(description="AI 답변 텍스트")
    answerable: bool = Field(description="사내 문서/코드 근거로 답변 가능 여부")
    citations: list[Citation] = Field(default_factory=list, description="답변 근거 출처 목록")
    suggested_post: SuggestedPost | None = Field(
        default=None, description="답변 불가 시 커뮤니티 게시글 초안"
    )


class ChatSessionCreateRequest(BaseModel):
    """ai-server가 직접 관리하는 채팅 세션 생성 요청."""

    title: str | None = Field(default=None, max_length=200, description="선택 세션 제목")


class ChatSessionResponse(BaseModel):
    """채팅 세션 응답."""

    model_config = ConfigDict(from_attributes=True)

    session_id: UUID
    user_id: int
    team_id: int | None = None
    title: str | None = None
    created_at: datetime
    updated_at: datetime


class ChatSessionListResponse(BaseModel):
    sessions: list[ChatSessionResponse] = Field(default_factory=list)
    next_cursor: str | None = Field(
        default=None, description="다음 페이지 커서 (마지막 세션 ID)"
    )
    has_more: bool = Field(default=False, description="추가 페이지 존재 여부")


class MessageResponse(BaseModel):
    """채팅 메시지 응답."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    role: Literal["user", "assistant"]
    content: str
    status: Literal["pending", "completed", "failed"] = "completed"
    failure_reason: str | None = None
    answerable: bool | None = None
    response_type: str | None = Field(
        default=None,
        description="응답 유형: 'rag' (RAG 기반) 또는 'general' (일반)",
    )
    citations: list[dict] = Field(default_factory=list)
    created_at: datetime


class ChatSessionDetailResponse(ChatSessionResponse):
    messages: list[MessageResponse] = Field(default_factory=list)
    next_message_cursor: str | None = Field(
        default=None, description="메시지 페이지네이션 커서"
    )
    has_more_messages: bool = Field(default=False, description="추가 메시지 존재 여부")


class SessionMessageRequest(BaseModel):
    """세션에 새 사용자 메시지를 전송하는 요청."""

    message: str = Field(min_length=1, description="사용자의 현재 질문")
    file_ids: list[UUID] = Field(
        default_factory=list,
        description="향후 파일 첨부 context에 사용할 업로드 파일 ID 목록",
    )


class SessionMessageResponse(ChatResponse):
    session_id: UUID
    user_message_id: UUID
    assistant_message_id: UUID
