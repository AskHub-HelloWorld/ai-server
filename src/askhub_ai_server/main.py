from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from askhub_ai_server.api.routes import chat, files, health, ingestion_jobs, sources
from askhub_ai_server.core.config import Settings, get_settings

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
        "name": "파일 관리",
        "description": "파일 업로드/조회 — 채팅 첨부 또는 RAG 소스 등록",
    },
    {
        "name": "ingestion-jobs",
        "description": "문서/코드 인덱싱 작업 관리",
    },
]


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    app = FastAPI(
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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(chat.router, prefix="/v1")
    app.include_router(files.router, prefix="/v1")
    app.include_router(sources.router, prefix="/v1")
    app.include_router(ingestion_jobs.router, prefix="/v1")
    return app


app = create_app()
