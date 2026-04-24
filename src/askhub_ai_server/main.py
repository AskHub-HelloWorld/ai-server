import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from askhub_ai_server.api.routes import chat, files, health, ingestion_jobs, sources
from askhub_ai_server.core.config import Settings, get_settings
from askhub_ai_server.core.database import SessionLocal
from askhub_ai_server.core.observability import ObservabilityMiddleware, configure_logging
from askhub_ai_server.services.exceptions import ServiceError
from askhub_ai_server.services.message_cleanup import cleanup_stale_pending_messages

logger = logging.getLogger(__name__)

TAGS_METADATA = [
    {
        "name": "health",
        "description": "서버 상태 확인",
    },
    {
        "name": "chat",
        "description": "세션 기반 AI 채팅 — 히스토리 저장 및 SSE 스트리밍 응답 지원",
    },
    {
        "name": "sources",
        "description": "RAG 소스 등록",
    },
    {
        "name": "files",
        "description": "파일 업로드/조회 — 채팅 첨부 또는 RAG 소스 등록",
    },
    {
        "name": "ingestion-jobs",
        "description": "문서/코드 인덱싱 작업 관리",
    },
]


def _run_startup_cleanup() -> None:
    """앱 시작 시 stale pending 메시지를 정리한다."""
    try:
        with SessionLocal() as db:
            cleanup_stale_pending_messages(db)
    except Exception:
        logger.warning("Startup pending message cleanup failed", exc_info=True)


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()

    configure_logging(resolved_settings.log_level)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        _run_startup_cleanup()
        yield

    app = FastAPI(
        lifespan=lifespan,
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        description=(
            "AskHub AI Server — 사내 개발자 대상 AI 챗봇 서비스\n\n"
            "## 주요 기능\n"
            "- **AI 채팅**: Amazon Bedrock Nova Lite를 활용한 질의응답\n"
            "- **SSE 스트리밍**: 실시간 토큰 단위 응답 전달\n"
            "- **대화 히스토리**: ai-server가 ai schema에서 직접 관리\n"
            "- **파일 관리**: 파일 업로드 및 채팅 첨부 지원\n\n"
            "## 아키텍처\n"
            "```\n"
            "Frontend → Backend(인증/인가)\n"
            "  → ai-server(히스토리+파일+RAG+LLM)\n"
            "  → Backend(SSE relay) → Frontend\n"
            "```\n"
            "MVP에서는 단일 EC2의 PostgreSQL 16 + pgvector 인스턴스를 공유하되, "
            "backend는 backend schema, ai-server는 ai schema만 소유합니다. "
            "공개 채팅 API는 세션 기반 endpoint만 사용하며, legacy chat endpoint는 제거했습니다."
        ),
        openapi_tags=TAGS_METADATA,
    )

    # --- Middleware (outermost first) ---
    app.add_middleware(ObservabilityMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Global exception handler for ServiceError ---
    @app.exception_handler(ServiceError)
    async def service_error_handler(_request: Request, exc: ServiceError) -> JSONResponse:
        request_id = getattr(_request.state, "request_id", "-")
        logger.warning(
            "ServiceError: %s %s",
            exc.error_code,
            exc.detail,
            extra={"error_code": exc.error_code, "request_id": request_id},
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.error_code,
                "detail": exc.detail,
                "request_id": request_id,
            },
        )

    # --- Routes ---
    app.include_router(health.router)
    app.include_router(chat.router, prefix="/v1")
    app.include_router(files.router, prefix="/v1")
    app.include_router(sources.router, prefix="/v1")
    app.include_router(ingestion_jobs.router, prefix="/v1")
    return app


app = create_app()
