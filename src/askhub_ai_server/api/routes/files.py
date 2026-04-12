"""파일 업로드/조회 API."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from tempfile import SpooledTemporaryFile
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from askhub_ai_server.core.config import Settings, get_settings
from askhub_ai_server.core.database import get_db
from askhub_ai_server.core.security import ServiceContext, get_service_context
from askhub_ai_server.models import ChatSession
from askhub_ai_server.models.file import UserFile
from askhub_ai_server.schemas.file import FileListResponse, FileUploadResponse
from askhub_ai_server.services.file_storage import StoredFile, get_file_storage

router = APIRouter(tags=["파일 관리"])
logger = logging.getLogger(__name__)


@router.post("/files/upload", response_model=FileUploadResponse, status_code=201)
async def upload_file(
    file: UploadFile,
    context: Annotated[ServiceContext, Depends(get_service_context)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[Session, Depends(get_db)],
    session_id: Annotated[
        uuid.UUID | None,
        Form(description="채팅 세션 ID (채팅 중 업로드 시)"),
    ] = None,
    purpose: Annotated[
        Literal["chat_attachment", "rag_source"],
        Form(),
    ] = "chat_attachment",
) -> FileUploadResponse:
    """파일을 업로드하고 메타데이터를 DB에 저장한다."""
    _validate_upload_content_type(file.content_type, settings)
    if session_id is not None:
        _get_owned_session_or_404(db, session_id, context)

    file_id = uuid.uuid4()
    original_filename = Path(file.filename or "unknown").name
    storage = get_file_storage(settings)

    file_size = 0
    stored_file: StoredFile | None = None
    upload_buffer = SpooledTemporaryFile(max_size=settings.max_upload_bytes)
    try:
        while chunk := await file.read(1024 * 1024):
            file_size += len(chunk)
            if file_size > settings.max_upload_bytes:
                raise HTTPException(
                    status_code=413,
                    detail="uploaded file exceeds the configured size limit",
                )
            upload_buffer.write(chunk)
        upload_buffer.seek(0)
        stored_file = storage.save_file(
            upload_buffer,
            user_id=context.user_id,
            file_id=file_id,
            filename=original_filename,
            content_type=file.content_type,
        )

        user_file = UserFile(
            id=file_id,
            user_id=context.user_id,
            team_id=context.team_id,
            session_id=session_id,
            filename=original_filename,
            content_type=file.content_type,
            file_size=file_size,
            storage_path=stored_file.path,
            storage_provider=stored_file.provider,
            storage_bucket=stored_file.bucket,
            storage_key=stored_file.key,
            purpose=purpose,
        )
        db.add(user_file)
        db.commit()
        db.refresh(user_file)
    except HTTPException:
        if stored_file is not None:
            storage.delete_file(stored_file)
        raise
    except Exception as exc:
        logger.exception("파일 업로드 저장 실패")
        db.rollback()
        if stored_file is not None:
            storage.delete_file(stored_file)
        raise HTTPException(status_code=500, detail="file upload failed") from exc
    finally:
        upload_buffer.close()

    return FileUploadResponse.model_validate(user_file)


@router.get("/files", response_model=FileListResponse)
def list_files(
    context: Annotated[ServiceContext, Depends(get_service_context)],
    db: Annotated[Session, Depends(get_db)],
) -> FileListResponse:
    """사용자의 업로드 파일 목록을 조회한다."""
    statement = select(UserFile).where(UserFile.user_id == context.user_id)
    if context.team_id is not None:
        statement = statement.where(UserFile.team_id == context.team_id)
    statement = statement.order_by(UserFile.created_at.desc())
    files = db.scalars(statement).all()
    return FileListResponse(files=[FileUploadResponse.model_validate(f) for f in files])


@router.get("/files/{file_id}", response_model=FileUploadResponse)
def get_file(
    file_id: uuid.UUID,
    context: Annotated[ServiceContext, Depends(get_service_context)],
    db: Annotated[Session, Depends(get_db)],
) -> FileUploadResponse:
    """파일 메타데이터를 조회한다."""
    user_file = db.get(UserFile, file_id)
    if not user_file or user_file.user_id != context.user_id:
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")
    if context.team_id is not None and user_file.team_id != context.team_id:
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")
    return FileUploadResponse.model_validate(user_file)


def _get_owned_session_or_404(
    db: Session,
    session_id: uuid.UUID,
    context: ServiceContext,
) -> ChatSession:
    session = db.get(ChatSession, session_id)
    if session is None or session.user_id != context.user_id:
        raise HTTPException(status_code=404, detail="채팅 세션을 찾을 수 없습니다.")
    if context.team_id is not None and session.team_id != context.team_id:
        raise HTTPException(status_code=404, detail="채팅 세션을 찾을 수 없습니다.")
    return session


def _validate_upload_content_type(content_type: str | None, _settings: Settings) -> None:
    if not content_type:
        raise HTTPException(status_code=400, detail="파일 content type이 필요합니다.")
    # 업로드 단계에서는 content-type을 차단하지 않는다.
    # 채팅/RAG 소비 시점에서 각 타입별로 처리를 결정한다.
    # (이미지 → image 블록, 문서 → document 블록, 텍스트 → UTF-8, 기타 → metadata)
