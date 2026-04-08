# AskHub AI Server

AskHub의 AI 챗봇 서비스. 사내 개발자들의 기술 질문에 AI가 답변하고, 채팅 세션과 메시지 히스토리를 직접 관리한다.

## 현재 구현 상태

- **세션 기반 AI 채팅**: `POST /v1/chat/sessions/{id}/messages`로 질의응답
- **SSE 스트리밍**: `POST /v1/chat/sessions/{id}/messages/stream`으로 실시간 토큰 단위 응답
- **멀티턴 대화**: ai-server가 `ai.messages`에서 이전 대화 히스토리를 직접 조회
- **DB 저장**: `ai.chat_sessions`, `ai.messages`를 SQLAlchemy/Alembic으로 관리
- **AI 응답**: Amazon Bedrock (Nova Micro) 또는 mock LLM 서비스 사용
- **자동 전환**: Bedrock 미연결 시 mock 모드로 동작
- **파일 업로드 API**: 이번 구현 범위에서는 보류

## 아키텍처

```
Frontend → Backend(인증/인가) → ai-server(히스토리+파일+RAG+LLM) → Backend(SSE relay) → Frontend
```

- MVP는 단일 EC2의 PostgreSQL 16 + pgvector 인스턴스를 backend와 ai-server가 공유한다.
- 단, backend는 `backend` schema, ai-server는 `ai` schema만 소유하고 migration/write 권한을 분리한다.
- 공개 채팅 API는 세션 기반 endpoint만 사용한다.
- 과거 legacy endpoint인 `POST /v1/chat`, `POST /v1/chat/stream`은 제거했다.

## API 엔드포인트

| Method | Path | 설명 |
|--------|------|------|
| GET | `/health` | 서버 상태 확인 |
| POST | `/v1/chat/sessions` | 채팅 세션 생성 |
| GET | `/v1/chat/sessions` | 채팅 세션 목록 조회 |
| GET | `/v1/chat/sessions/{session_id}` | 채팅 세션 상세 및 메시지 히스토리 조회 |
| POST | `/v1/chat/sessions/{session_id}/messages` | 세션 메시지 전송 (non-streaming) |
| POST | `/v1/chat/sessions/{session_id}/messages/stream` | 세션 메시지 전송 (SSE streaming) |
| POST | `/v1/sources` | RAG 소스 등록 (Phase 2 mock) |
| POST | `/v1/ingestion-jobs` | 인덱싱 작업 생성 (Phase 2 mock) |
| GET | `/v1/ingestion-jobs/{job_id}` | 인덱싱 작업 조회 (Phase 2 mock) |

Swagger UI: `http://localhost:8000/docs`

## 로컬 개발 환경

필수 도구: Docker Desktop

```bash
cp .env.example .env
# .env에 AWS_BEARER_TOKEN_BEDROCK 설정 (미설정 시 mock 모드)
docker compose up --build api
```

헬스 체크:

```bash
curl http://localhost:8000/health
```

테스트:

```bash
docker compose run --rm api pytest
```

린트:

```bash
docker compose run --rm api ruff check .
```

DB 마이그레이션:

```bash
docker compose up -d postgres
docker compose run --rm api alembic upgrade head
```

## 기술 스택

- Python 3.12 / FastAPI
- Amazon Bedrock (Nova Micro — `amazon.nova-micro-v1:0`)
- boto3 / SSE (Server-Sent Events)
- PostgreSQL 16 / pgvector / SQLAlchemy / Alembic
- Docker / Docker Compose

## 문서

- 전체 아키텍처와 후속 작업: `docs/architecture.md`
- 개발 계획: `docs/development-plan.md`
- API 계약: `docs/api-contract.md`
