"""파일 관리 서비스 — DB 조회/저장 로직을 route에서 분리."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from askhub_ai_server.core.config import Settings
from askhub_ai_server.core.security import ServiceContext
from askhub_ai_server.models import ChatSession
from askhub_ai_server.models.enums import FilePurpose
from askhub_ai_server.models.file import UserFile
from askhub_ai_server.services.exceptions import ServiceError
from askhub_ai_server.services.pagination import PaginatedResult, paginate_query

PaginatedFiles = PaginatedResult[UserFile]


class FileService:
    def __init__(self, db: Session, settings: Settings) -> None:
        self._db = db
        self._settings = settings

    def list_files(
        self,
        context: ServiceContext,
        *,
        cursor: uuid.UUID | None = None,
        limit: int = 20,
    ) -> PaginatedFiles:
        clamped_limit = min(limit, self._settings.max_page_limit)

        stmt = select(UserFile).where(UserFile.user_id == context.user_id)
        if context.team_id is not None:
            stmt = stmt.where(UserFile.team_id == context.team_id)

        return paginate_query(
            self._db,
            stmt,
            model_class=UserFile,
            cursor=cursor,
            limit=clamped_limit,
            order_column=UserFile.created_at,
            id_column=UserFile.id,
            descending=True,
        )

    def get_file(self, file_id: uuid.UUID, context: ServiceContext) -> UserFile:
        user_file = self._db.get(UserFile, file_id)
        if not user_file or user_file.user_id != context.user_id:
            raise ServiceError(404, "파일을 찾을 수 없습니다.")
        if context.team_id is not None and user_file.team_id != context.team_id:
            raise ServiceError(404, "파일을 찾을 수 없습니다.")
        return user_file

    def get_file_for_download(
        self, file_id: uuid.UUID, context: ServiceContext,
    ) -> UserFile:
        user_file = self._db.get(UserFile, file_id)
        if user_file is None or not self._can_access_for_download(user_file, context):
            raise ServiceError(404, "파일을 찾을 수 없습니다.")
        return user_file

    def require_owned_session(
        self, session_id: uuid.UUID, context: ServiceContext,
    ) -> ChatSession:
        session = self._db.get(ChatSession, session_id)
        if session is None or session.user_id != context.user_id:
            raise ServiceError(404, "채팅 세션을 찾을 수 없습니다.")
        if context.team_id is not None and session.team_id != context.team_id:
            raise ServiceError(404, "채팅 세션을 찾을 수 없습니다.")
        return session

    @staticmethod
    def _can_access_for_download(user_file: UserFile, context: ServiceContext) -> bool:
        if user_file.user_id == context.user_id:
            if context.team_id is not None and user_file.team_id != context.team_id:
                return False
            return True
        return (
            user_file.purpose == FilePurpose.RAG_SOURCE
            and context.team_id is not None
            and user_file.team_id == context.team_id
        )
