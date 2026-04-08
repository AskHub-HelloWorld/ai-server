# AskHub AI Server 개발 계획

권장 전체 아키텍처와 후속 작업 목록은 `docs/architecture.md`를 기준으로 한다.

## Phase 0. 레포지토리 부트스트랩 ✅

- Python/FastAPI 프로젝트 구조를 만든다.
- health API와 mock chat API를 추가한다.
- env 템플릿, multi-stage Dockerfile, compose.yaml, 기본 테스트를 추가한다.
- 로컬 실행, 테스트, 린트는 Docker Compose 기준으로 통일한다.

## Phase 1. 기본 AI 채팅 ✅

- `GET /health`: 프로세스와 설정 상태를 확인한다.
- Bedrock LLM(Amazon Nova Micro)과 mock LLM 서비스를 구현한다.
- Bedrock 미연결 시 mock 모드로 자동 전환한다.
- `POST /v1/sources`, `POST /v1/ingestion-jobs`, `GET /v1/ingestion-jobs/{job_id}`: mock 스캐폴딩.
- 과거 공개 API였던 `POST /v1/chat`, `POST /v1/chat/stream`은 세션 기반 API 전환 후 제거했다.

## Phase 2. DB 연결 + 채팅 히스토리

- PostgreSQL 연결 설정을 추가한다 (SQLAlchemy + psycopg + pgvector). → 완료
- 단일 EC2 공통 PostgreSQL 인스턴스를 사용하되 ai-server 전용 `ai` schema를 사용한다. → 완료
- Alembic 마이그레이션을 초기화하고 `ai` schema에 ai-server 전용 테이블을 생성한다. → 완료
- MVP에서는 backend `users`, `teams` 테이블로 강한 FK를 걸지 않고 backend가 검증한 `user_id`, `team_id` 값을 저장한다.
- 채팅 세션/메시지 모델을 만들고 세션 기반 채팅 API로 전환한다.
  - `POST /v1/chat/sessions`: 새 세션 생성. → 완료
  - `GET /v1/chat/sessions`: 사용자의 세션 목록 조회. → 완료
  - `GET /v1/chat/sessions/{id}`: 세션 상세와 메시지 조회. → 완료
  - `POST /v1/chat/sessions/{id}/messages`: 세션 내 메시지 전송. → 완료
  - `POST /v1/chat/sessions/{id}/messages/stream`: 세션 내 메시지 전송 (SSE). → 완료
- ai-server가 히스토리를 직접 DB에서 조회/저장하도록 변경한다. → 완료
- 실제 FastAPI 호출로 세션 생성, non-streaming 메시지 저장, SSE 메시지 저장을 검증한다. → 완료
- 기존 `POST /v1/chat`, `POST /v1/chat/stream`은 세션 기반 API로 대체하고 제거한다. → 완료
- 파일 업로드 API는 이번 구현 범위에서 스킵한다.

## Phase 2-후속. 파일 관리

- `user_files` 모델을 만든다.
- `POST /v1/files/upload`: 파일 업로드 (채팅 첨부 또는 RAG 소스).
- `GET /v1/files/{file_id}`: 파일 메타데이터 조회.
- MVP에서는 Docker Volume에, 운영에서는 S3에 파일을 저장한다.
- 세션 메시지 API의 `file_ids`를 실제 파일 context 주입 로직과 연결한다.

## Phase 3. RAG (pgvector)

- Bedrock Titan Embed를 호출하여 임베딩을 생성하는 서비스를 만든다.
- `PgVectorRetriever`를 구현한다 (team_id 필터 + cosine similarity 검색).
- 채팅 API에 RAG 검색 결과를 LLM context로 주입하는 로직을 통합한다.
- `AnswerPolicy`를 만들어 검색 근거 부족 시 `answerable=false`를 판단한다.
- `CitationBuilder`를 만들어 검색 metadata를 citation 형식으로 변환한다.
- 검색 근거가 약하면 `suggested_post`(커뮤니티 게시글 초안)를 반환한다.

## Phase 4. Ingestion Worker

- worker process를 실제 job loop로 바꾼다.
- GitHub repo 코드를 수집하는 loader를 만든다.
- 사내 문서를 수집하는 loader를 만든다.
- 수집한 파일을 chunk로 분할하고, 임베딩을 생성하여 `document_chunks`에 저장한다.
- `rag_sources`, `ingestion_jobs` 테이블로 소스 등록과 작업 상태를 관리한다.
- 로컬에서는 `docker compose --profile worker up worker`로 worker를 실행한다.

## Phase 5. 보안과 배포

- backend가 전달한 user/team context를 검증하는 middleware를 추가한다.
- retrieval filter에 team ID를 강제한다.
- prompt injection 방어용 system prompt 정책을 추가한다.
- Docker image를 ECR에 push하고 EC2에 배포한다.
- EC2 루트 compose에서는 backend, ai-server, PostgreSQL 16 + pgvector, uploads volume을 함께 올린다.
- DB 계정은 가능하면 `backend_user`, `ai_user`로 분리하고 각 schema 권한만 부여한다.
