"""파일 업로드/조회 API."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from tempfile import SpooledTemporaryFile
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from askhub_ai_server.core.config import Settings, get_settings
from askhub_ai_server.core.database import get_db
from askhub_ai_server.core.security import ServiceContext, get_service_context
from askhub_ai_server.models.enums import FilePurpose
from askhub_ai_server.models.file import UserFile
from askhub_ai_server.schemas.file import FileListResponse, FileUploadResponse
from askhub_ai_server.services.exceptions import ServiceError
from askhub_ai_server.services.file_service import FileService
from askhub_ai_server.services.file_storage import StoredFile, get_file_storage

router = APIRouter(tags=["files"])
logger = logging.getLogger(__name__)


def _get_file_service(
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> FileService:
    return FileService(db, settings)


def _http_exception(error: ServiceError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=error.detail)


@router.post("/files/upload", response_model=FileUploadResponse, status_code=201)
async def upload_file(
    file: UploadFile,
    context: Annotated[ServiceContext, Depends(get_service_context)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[Session, Depends(get_db)],
    service: Annotated[FileService, Depends(_get_file_service)],
    session_id: Annotated[
        uuid.UUID | None,
        Form(description="채팅 세션 ID (채팅 중 업로드 시)"),
    ] = None,
    purpose: Annotated[
        FilePurpose,
        Form(),
    ] = FilePurpose.CHAT_ATTACHMENT,
) -> FileUploadResponse:
    """파일을 업로드하고 메타데이터를 DB에 저장한다."""
    _validate_upload_content_type(file.content_type, settings)
    if session_id is not None:
        try:
            service.require_owned_session(session_id, context)
        except ServiceError as exc:
            raise _http_exception(exc) from exc

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

    return _file_response(user_file)


@router.get("/files", response_model=FileListResponse)
def list_files(
    context: Annotated[ServiceContext, Depends(get_service_context)],
    service: Annotated[FileService, Depends(_get_file_service)],
    cursor: Annotated[
        uuid.UUID | None,
        Query(description="이전 페이지 마지막 파일 ID"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100, description="페이지 크기")] = 20,
) -> FileListResponse:
    """사용자의 업로드 파일 목록을 조회한다 (cursor-based pagination)."""
    page = service.list_files(context, cursor=cursor, limit=limit)
    return FileListResponse(
        files=[_file_response(f) for f in page.items],
        next_cursor=str(page.next_cursor) if page.next_cursor else None,
        has_more=page.has_more,
    )


@router.get("/files/{file_id}", response_model=FileUploadResponse)
def get_file(
    file_id: uuid.UUID,
    context: Annotated[ServiceContext, Depends(get_service_context)],
    service: Annotated[FileService, Depends(_get_file_service)],
) -> FileUploadResponse:
    """파일 메타데이터를 조회한다."""
    try:
        user_file = service.get_file(file_id, context)
    except ServiceError as exc:
        raise _http_exception(exc) from exc
    return _file_response(user_file)


@router.get("/files/{file_id}/download", status_code=302)
def download_file(
    file_id: uuid.UUID,
    context: Annotated[ServiceContext, Depends(get_service_context)],
    service: Annotated[FileService, Depends(_get_file_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RedirectResponse:
    """권한 검증 후 S3 presigned URL로 리다이렉트한다."""
    try:
        user_file = service.get_file_for_download(file_id, context)
    except ServiceError as exc:
        raise _http_exception(exc) from exc

    storage = get_file_storage(settings)
    try:
        url = storage.generate_download_url(user_file)
    except Exception as exc:
        logger.exception("파일 다운로드 URL 생성 실패")
        raise HTTPException(status_code=500, detail="file download failed") from exc
    return RedirectResponse(url=url, status_code=302)


# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------


def _classify_file(content_type: str | None, filename: str) -> tuple[str, str]:
    """파일의 content_type과 filename으로 종류(kind)와 표시 라벨을 반환한다."""
    hint = f"{content_type or ''} {filename}".lower()
    if "pdf" in hint:
        return "pdf", "PDF"
    if "spreadsheetml" in hint or hint.endswith((".xlsx", ".xls", ".csv")):
        return "spreadsheet", "스프레드시트"
    if (
        "wordprocessingml" in hint
        or "presentationml" in hint
        or hint.endswith((".docx", ".doc", ".pptx", ".ppt"))
    ):
        return "document", "문서"
    if (content_type or "").startswith("image/"):
        return "image", "이미지"
    if (content_type or "").startswith("text/") or "json" in hint or "xml" in hint:
        return "text", "텍스트"
    return "file", "파일"


def _file_response(user_file: UserFile) -> FileUploadResponse:
    """UserFile ORM 객체를 FileUploadResponse로 변환하며 file_kind 필드를 채운다."""
    resp = FileUploadResponse.model_validate(user_file)
    kind, label = _classify_file(user_file.content_type, user_file.filename)
    resp.file_kind = kind
    resp.file_kind_label = label
    return resp


def _validate_upload_content_type(content_type: str | None, settings: Settings) -> None:
    if not content_type:
        raise HTTPException(status_code=400, detail="파일 content type이 필요합니다.")
    if content_type.lower() not in settings.allowed_upload_content_types:
        raise HTTPException(
            status_code=400,
            detail=f"허용되지 않는 파일 형식입니다: {content_type}",
        )
