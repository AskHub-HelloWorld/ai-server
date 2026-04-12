# AskHub AI Server

AskHub의 AI 챗봇 서비스. 사내 개발자들의 기술 질문에 AI가 답변하고, 채팅 세션과 메시지 히스토리를 직접 관리한다.

## 현재 구현 상태

- **세션 기반 AI 채팅**: `POST /v1/chat/sessions/{id}/messages`로 질의응답
- **SSE 스트리밍**: `POST /v1/chat/sessions/{id}/messages/stream`으로 실시간 토큰 단위 응답
- **멀티턴 대화**: ai-server가 `ai.messages`에서 이전 대화 히스토리를 직접 조회
- **DB 저장**: `ai.chat_sessions`, `ai.messages`, `ai.user_files`, `ai.rag_sources`, `ai.ingestion_jobs`를 SQLAlchemy/Alembic으로 관리
- **AI 응답**: Amazon Bedrock Nova Lite를 실제 호출하며 mock fallback은 사용하지 않음
- **서비스 인증**: backend가 서명한 service-to-service 헤더만 신뢰
- **파일 업로드 API**: 채팅 첨부 파일 업로드/조회 및 LLM context 반영
- **RAG 소스/작업 API**: source/job metadata를 DB에 영속화. 실제 ingestion worker는 후속 구현 범위

## 아키텍처

```
Frontend → Backend(인증/인가) → ai-server(히스토리+파일+RAG+LLM) → Backend(SSE relay) → Frontend
```

- MVP는 단일 EC2의 PostgreSQL 16 + pgvector 인스턴스를 backend와 ai-server가 공유한다.
- PostgreSQL 컨테이너는 `backend` 레포의 compose에서 띄우고, ai-server는 같은 Docker network에 붙어 `ai` schema만 사용한다.
- 단, backend는 `backend` schema, ai-server는 `ai` schema만 소유하고 migration/write 권한을 분리한다.
- 공개 채팅 API는 세션 기반 endpoint만 사용한다.
- 과거 legacy endpoint인 `POST /v1/chat`, `POST /v1/chat/stream`은 제거했다.

## API 엔드포인트

| Method | Path | 설명 |
|--------|------|------|
| GET | `/health` | 서버 상태 확인 |
| GET | `/ready` | DB/설정 readiness 확인 |
| POST | `/v1/chat/sessions` | 채팅 세션 생성 |
| GET | `/v1/chat/sessions` | 채팅 세션 목록 조회 |
| GET | `/v1/chat/sessions/{session_id}` | 채팅 세션 상세 및 메시지 히스토리 조회 |
| POST | `/v1/chat/sessions/{session_id}/messages` | 세션 메시지 전송 (non-streaming) |
| POST | `/v1/chat/sessions/{session_id}/messages/stream` | 세션 메시지 전송 (SSE streaming) |
| POST | `/v1/files/upload` | 채팅 첨부/RAG 소스 파일 업로드 |
| GET | `/v1/files` | 업로드 파일 목록 조회 |
| GET | `/v1/files/{file_id}` | 업로드 파일 메타데이터 조회 |
| POST | `/v1/sources` | RAG 소스 등록 |
| POST | `/v1/ingestion-jobs` | 인덱싱 작업 metadata 생성 |
| GET | `/v1/ingestion-jobs/{job_id}` | 인덱싱 작업 조회 |

Swagger UI: `http://localhost:8000/docs`

## 로컬 개발 환경

필수 도구: Docker Desktop

1. `backend/.env.example`을 기준으로 `backend/.env`를 만들고, `POSTGRES_*`, `ASKHUB_DOCKER_NETWORK`를 설정한다.
2. `backend`에서 `docker compose up -d postgres`로 pgvector 지원 PostgreSQL을 띄운다.
3. `ai-server/.env.example`을 기준으로 `ai-server/.env`를 만들고, 같은 DB/network 값과 `SERVICE_AUTH_SECRET`, Bedrock 자격 증명을 설정한다.
4. `ai-server`에서 `docker compose --profile tools run --rm migrate`로 `ai` schema migration을 적용한다.
5. `ai-server`에서 `docker compose up --build api`로 API를 실행한다.

헬스 체크:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

테스트:

```bash
docker compose run --rm -e RUN_LIVE_BEDROCK_TESTS=1 api-test pytest
```

린트:

```bash
docker compose run --rm api-test ruff check .
```

DB 마이그레이션:

```bash
docker compose --profile tools run --rm migrate
```

## 기술 스택

- Python 3.12 / FastAPI
- Amazon Bedrock (Amazon Nova Lite — `amazon.nova-lite-v1:0`)
- boto3 / SSE (Server-Sent Events)
- PostgreSQL 16 / pgvector / SQLAlchemy / Alembic
- Docker / Docker Compose

## 문서

- 전체 아키텍처와 후속 작업: `docs/architecture.md`
- 개발 계획: `docs/development-plan.md`
- API 계약: `docs/api-contract.md`
