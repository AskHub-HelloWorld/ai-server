# AskHub AI Server

AskHub의 AI 챗봇 및 RAG 오케스트레이션 서비스입니다. backend가 인증한 사용자/팀 context를 받아 채팅 세션, 메시지 히스토리, 파일 첨부, RAG 검색, Bedrock LLM 호출을 처리합니다.

## 현재 구현 상태

- **세션 기반 AI 채팅**: `POST /v1/chat/sessions/{session_id}/messages`
- **SSE 스트리밍**: `POST /v1/chat/sessions/{session_id}/messages/stream`
- **대화 히스토리 관리**: ai-server가 `ai.chat_sessions`, `ai.messages`를 직접 조회/저장
- **파일 관리**: S3 기반 파일 저장, metadata DB 저장, 채팅 첨부 context 반영
- **RAG 소스 관리**: `rag_sources`, `ingestion_jobs`, `document_chunks`를 DB에 저장
- **Ingestion worker**: repository/document source를 chunking, embedding 후 pgvector에 저장
- **AI 응답**: Amazon Bedrock Nova Lite 호출. mock fallback은 사용하지 않음
- **서비스 인증**: backend가 서명한 service-to-service HMAC 헤더만 신뢰

## Docker Only

이 프로젝트의 실행, 테스트, 린트, 마이그레이션은 **Docker Compose 안에서만** 수행합니다. 로컬 Python, 로컬 pytest, 로컬 ruff, 로컬 uvicorn 실행은 공식 개발 경로가 아닙니다.

필수 도구:

- Docker Desktop
- backend 레포의 PostgreSQL/pgvector compose 환경

대표 명령:

```bash
docker compose --profile tools run --rm migrate
docker compose up --build api
docker compose --profile worker up --build worker
docker compose run --rm api-test pytest
docker compose run --rm api-test ruff check .
```

자세한 로컬 실행 절차는 [docs/local-docker.md](docs/local-docker.md)를 봅니다.

## 아키텍처 요약

```text
Frontend -> Backend(인증/인가) -> ai-server(히스토리+파일+RAG+LLM) -> Backend(SSE relay) -> Frontend
```

- frontend는 ai-server를 직접 호출하지 않습니다.
- backend는 사용자/팀 권한을 검증한 뒤 service-to-service HMAC 헤더로 ai-server에 전달합니다.
- backend와 ai-server는 같은 PostgreSQL 인스턴스를 공유할 수 있지만 schema ownership은 분리합니다.
- backend는 `backend` schema, ai-server는 `ai` schema만 소유하고 마이그레이션합니다.
- 업로드 파일 본문은 S3에 저장하고 DB에는 metadata와 storage path만 저장합니다.

상세 구조는 [docs/architecture.md](docs/architecture.md)를 봅니다.

## 주요 API

| Method | Path | 설명 |
|--------|------|------|
| GET | `/health` | 프로세스 상태 확인 |
| GET | `/ready` | DB/설정 readiness 확인 |
| POST | `/v1/chat/sessions` | 채팅 세션 생성 |
| GET | `/v1/chat/sessions` | 채팅 세션 목록 조회 |
| GET | `/v1/chat/sessions/{session_id}` | 채팅 세션 상세 및 메시지 조회 |
| POST | `/v1/chat/sessions/{session_id}/messages` | 세션 메시지 전송 |
| POST | `/v1/chat/sessions/{session_id}/messages/stream` | 세션 메시지 SSE 스트리밍 |
| POST | `/v1/files/upload` | 채팅 첨부/RAG 소스 파일 업로드 |
| GET | `/v1/files` | 업로드 파일 목록 조회 |
| GET | `/v1/files/{file_id}` | 업로드 파일 metadata 조회 |
| GET | `/v1/files/{file_id}/download` | 파일 다운로드 redirect |
| POST | `/v1/sources` | RAG 소스 등록 |
| GET | `/v1/sources` | RAG 소스 목록 조회 |
| DELETE | `/v1/sources/{source_id}` | RAG 소스 삭제 |
| POST | `/v1/ingestion-jobs` | 인덱싱 작업 생성 |
| GET | `/v1/ingestion-jobs/{job_id}` | 인덱싱 작업 조회 |

Swagger UI는 API 컨테이너 실행 후 `http://localhost:8000/docs`에서 확인합니다.

API 계약은 [docs/api-contract.md](docs/api-contract.md)를 봅니다.

## 프로젝트 구조

```text
ai-server/
  src/askhub_ai_server/   # FastAPI 앱, 도메인 서비스, 모델, 스키마
  alembic/                # ai schema DB migration
  tests/                  # Docker Compose 기반 테스트
  docs/                   # 아키텍처, API 계약, Docker 실행 문서
  scripts/                # 보조 스크립트
  chatbot-test-ui/        # 로컬 전용 Docker 기반 수동 테스트 UI
  compose.yaml            # api, worker, api-test, migrate 서비스
```

## 문서

- [Docker 로컬 실행](docs/local-docker.md)
- [아키텍처](docs/architecture.md)
- [API 계약](docs/api-contract.md)
- [개발 계획](docs/development-plan.md)
