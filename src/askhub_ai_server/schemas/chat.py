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


class Citation(BaseModel):
    """답변 근거 출처 (Phase 2 RAG에서 사용 예정)."""

    title: str
    source_type: str
    url: str | None = None
    repo: str | None = None
    path: str | None = None
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

    user_id: int = Field(description="Backend에서 검증한 사용자 ID")
    team_id: int | None = Field(default=None, description="Backend에서 검증한 팀 ID")
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


class MessageResponse(BaseModel):
    """채팅 메시지 응답."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    role: Literal["user", "assistant"]
    content: str
    answerable: bool | None = None
    citations: list[dict] = Field(default_factory=list)
    created_at: datetime


class ChatSessionDetailResponse(ChatSessionResponse):
    messages: list[MessageResponse] = Field(default_factory=list)


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
