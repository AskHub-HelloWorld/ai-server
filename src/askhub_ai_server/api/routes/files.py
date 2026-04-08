"""파일 업로드/조회 API."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from askhub_ai_server.core.config import get_settings
from askhub_ai_server.core.database import get_db
from askhub_ai_server.models.file import UserFile
from askhub_ai_server.schemas.file import FileListResponse, FileUploadResponse

router = APIRouter(tags=["파일 관리"])

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


@router.post("/files/upload", response_model=FileUploadResponse, status_code=201)
async def upload_file(
    file: UploadFile,
    user_id: int = Form(..., description="사용자 ID"),
    team_id: int | None = Form(None, description="팀 ID"),
    session_id: uuid.UUID | None = Form(None, description="채팅 세션 ID (채팅 중 업로드 시)"),
    purpose: Literal["chat_attachment", "rag_source"] = Form("chat_attachment"),
    db: Session = Depends(get_db),
) -> FileUploadResponse:
    """파일을 업로드하고 메타데이터를 DB에 저장한다."""
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="파일 크기가 10MB를 초과합니다.")

    settings = get_settings()
    file_id = uuid.uuid4()
    safe_filename = file.filename or "unknown"
    storage_dir = Path(settings.upload_dir) / str(user_id)
    storage_dir.mkdir(parents=True, exist_ok=True)
    storage_path = storage_dir / f"{file_id}_{safe_filename}"

    with open(storage_path, "wb") as f:
        f.write(content)

    user_file = UserFile(
        id=file_id,
        user_id=user_id,
        team_id=team_id,
        session_id=session_id,
        filename=safe_filename,
        content_type=file.content_type,
        file_size=len(content),
        storage_path=str(storage_path),
        purpose=purpose,
    )
    db.add(user_file)
    db.commit()
    db.refresh(user_file)

    return FileUploadResponse.model_validate(user_file)


@router.get("/files", response_model=FileListResponse)
def list_files(
    user_id: int,
    db: Session = Depends(get_db),
) -> FileListResponse:
    """사용자의 업로드 파일 목록을 조회한다."""
    files = (
        db.query(UserFile)
        .filter(UserFile.user_id == user_id)
        .order_by(UserFile.created_at.desc())
        .all()
    )
    return FileListResponse(files=[FileUploadResponse.model_validate(f) for f in files])


@router.get("/files/{file_id}", response_model=FileUploadResponse)
def get_file(
    file_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> FileUploadResponse:
    """파일 메타데이터를 조회한다."""
    user_file = db.get(UserFile, file_id)
    if not user_file:
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")
    return FileUploadResponse.model_validate(user_file)
