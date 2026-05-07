# AskHub AI Server

AI 챗봇 및 RAG 오케스트레이션 FastAPI 서버입니다. 이 문서는 서버를 가동하고 API를 호출하는 방법을 안내합니다.

---

## 빠른 시작

### 전제 조건

| 항목 | 설명 |
|------|------|
| Docker Desktop | 실행 중이어야 합니다 |
| backend PostgreSQL | backend 레포의 `docker compose up -d postgres`로 띄운 상태 |
| AWS 자격증명 | Bedrock (LLM/Embedding) 및 S3 접근 가능한 IAM 키 |

### 1단계: 환경 변수 설정

```bash
cp .env.example .env
```

`.env`에서 아래 필수 값을 채웁니다:

```dotenv
# PostgreSQL (backend와 동일한 DB)
POSTGRES_HOST=postgres
POSTGRES_DB=askhub
POSTGRES_USER=askhub
POSTGRES_PASSWORD=<비밀번호>

# 서비스 간 인증 시크릿 (backend와 동일한 값)
SERVICE_AUTH_SECRET=<랜덤 시크릿>

# AWS (Bedrock + S3)
AWS_ACCESS_KEY_ID=<액세스 키>
AWS_SECRET_ACCESS_KEY=<시크릿 키>
S3_BUCKET=<S3 버킷명>
S3_REGION=ap-northeast-2
```

### 2단계: DB 마이그레이션

```bash
docker compose --profile tools run --rm migrate
```

### 3단계: API 서버 실행

```bash
docker compose up --build api
```

서버가 정상 가동되면 아래 URL로 확인합니다:

```bash
# 헬스 체크
curl http://localhost:8000/health
# 응답: {"service":"AskHub AI Server","environment":"local","version":"0.1.0","status":"ok"}

# DB 연결 확인
curl http://localhost:8000/ready
```

Swagger UI (대화형 API 문서): http://localhost:8000/docs

### 4단계 (선택): Ingestion Worker 실행

RAG 소스 인덱싱이 필요하면 별도 터미널에서 실행합니다:

```bash
docker compose --profile worker up --build worker
```

---

## API 인증

모든 `/v1/*` 엔드포인트는 HMAC-SHA256 서비스 인증이 필요합니다. backend 서버가 사용자 인증 후 아래 헤더를 붙여 ai-server를 호출합니다.

### 필수 헤더

| 헤더 | 설명 |
|------|------|
| `x-askhub-user-id` | 인증된 사용자 ID (정수) |
| `x-askhub-team-id` | 팀 ID (정수, 없으면 빈 문자열) |
| `x-askhub-timestamp` | Unix epoch 초 (현재 시각 기준 ±300초 이내) |
| `x-askhub-signature` | HMAC-SHA256 서명값 |

### 서명 생성 방법

서명 payload는 아래 필드를 줄바꿈(`\n`)으로 연결한 문자열입니다:

```
{timestamp}\n{METHOD}\n{path}\n{query}\n{user_id}\n{team_id}
```

Python 예시:

```python
import hmac
import time
from hashlib import sha256

SECRET = "your-service-auth-secret"

def sign_request(method: str, path: str, user_id: int, team_id: int | None = None, query: str = ""):
    timestamp = str(int(time.time()))
    team_id_str = "" if team_id is None else str(team_id)
    payload = "\n".join([timestamp, method.upper(), path, query, str(user_id), team_id_str])
    signature = hmac.new(SECRET.encode(), payload.encode(), sha256).hexdigest()
    return {
        "x-askhub-user-id": str(user_id),
        "x-askhub-team-id": team_id_str,
        "x-askhub-timestamp": timestamp,
        "x-askhub-signature": signature,
    }

# 사용 예:
headers = sign_request("POST", "/v1/chat/sessions", user_id=1, team_id=1)
```

### 로컬 테스트 팁

아래 Bash 함수를 사용하면 cURL 호출 시 인증 헤더를 자동 생성할 수 있습니다:

```bash
sign() {
  local METHOD="$1" PATH="$2" USER_ID="${3:-1}" TEAM_ID="${4:-1}" QUERY="${5:-}"
  local TS=$(date +%s)
  local PAYLOAD="${TS}\n${METHOD}\n${PATH}\n${QUERY}\n${USER_ID}\n${TEAM_ID}"
  local SIG=$(printf "$PAYLOAD" | openssl dgst -sha256 -hmac "$SERVICE_AUTH_SECRET" | awk '{print $2}')
  echo "-H 'x-askhub-user-id: ${USER_ID}' -H 'x-askhub-team-id: ${TEAM_ID}' -H 'x-askhub-timestamp: ${TS}' -H 'x-askhub-signature: ${SIG}'"
}
```

---

## API 사용 예시

### 채팅 세션 생성

```bash
curl -X POST http://localhost:8000/v1/chat/sessions \
  -H "Content-Type: application/json" \
  -H "x-askhub-user-id: 1" \
  -H "x-askhub-team-id: 1" \
  -H "x-askhub-timestamp: $(date +%s)" \
  -H "x-askhub-signature: <서명값>" \
  -d '{"title": "테스트 세션"}'
```

응답:
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": 1,
  "team_id": 1,
  "title": "테스트 세션",
  "created_at": "2025-01-01T00:00:00Z",
  "updated_at": "2025-01-01T00:00:00Z"
}
```

### 메시지 전송 (동기)

```bash
curl -X POST http://localhost:8000/v1/chat/sessions/{session_id}/messages \
  -H "Content-Type: application/json" \
  -H "x-askhub-user-id: 1" \
  -H "x-askhub-team-id: 1" \
  -H "x-askhub-timestamp: <timestamp>" \
  -H "x-askhub-signature: <서명값>" \
  -d '{"message": "안녕하세요, AskHub에 대해 알려주세요"}'
```

응답:
```json
{
  "session_id": "...",
  "user_message_id": "...",
  "assistant_message_id": "...",
  "answer": "안녕하세요! AskHub는...",
  "answerable": true,
  "citations": [],
  "suggested_post": null
}
```

### 메시지 전송 (SSE 스트리밍)

```bash
curl -N -X POST http://localhost:8000/v1/chat/sessions/{session_id}/messages/stream \
  -H "Content-Type: application/json" \
  -H "x-askhub-user-id: 1" \
  -H "x-askhub-team-id: 1" \
  -H "x-askhub-timestamp: <timestamp>" \
  -H "x-askhub-signature: <서명값>" \
  -d '{"message": "RAG 기능을 설명해주세요"}'
```

SSE 이벤트 형식:
```
event: metadata
data: {"session_id": "...", "user_message_id": "...", "assistant_message_id": "..."}

event: token
data: {"delta": "RAG는 "}

event: token
data: {"delta": "Retrieval-Augmented "}

event: done
data: {"session_id": "...", "full_response": "RAG는 Retrieval-Augmented...", "answerable": true, "citations": [...]}
```

### 파일 업로드

```bash
curl -X POST http://localhost:8000/v1/files/upload \
  -H "x-askhub-user-id: 1" \
  -H "x-askhub-team-id: 1" \
  -H "x-askhub-timestamp: <timestamp>" \
  -H "x-askhub-signature: <서명값>" \
  -F "file=@document.pdf" \
  -F "purpose=chat_attachment" \
  -F "session_id={session_id}"
```

파일 첨부 후 메시지 전송:
```bash
curl -X POST http://localhost:8000/v1/chat/sessions/{session_id}/messages \
  -H "Content-Type: application/json" \
  -H "x-askhub-user-id: 1" \
  -H "x-askhub-team-id: 1" \
  -H "x-askhub-timestamp: <timestamp>" \
  -H "x-askhub-signature: <서명값>" \
  -d '{"message": "이 문서를 요약해주세요", "file_ids": ["<업로드된 file_id>"]}'
```

### RAG 소스 등록 및 인덱싱

```bash
# 1. 소스 등록 (GitHub 저장소)
curl -X POST http://localhost:8000/v1/sources \
  -H "Content-Type: application/json" \
  -H "x-askhub-user-id: 1" \
  -H "x-askhub-team-id: 1" \
  -H "x-askhub-timestamp: <timestamp>" \
  -H "x-askhub-signature: <서명값>" \
  -d '{"source_type": "repository", "name": "My Repo", "repo_url": "https://github.com/org/repo"}'

# 2. 인덱싱 작업 생성 (Worker가 처리)
curl -X POST http://localhost:8000/v1/ingestion-jobs \
  -H "Content-Type: application/json" \
  -H "x-askhub-user-id: 1" \
  -H "x-askhub-team-id: 1" \
  -H "x-askhub-timestamp: <timestamp>" \
  -H "x-askhub-signature: <서명값>" \
  -d '{"source_id": "<등록된 source_id>", "mode": "full"}'

# 3. 인덱싱 상태 확인
curl http://localhost:8000/v1/ingestion-jobs/{job_id} \
  -H "x-askhub-user-id: 1" \
  -H "x-askhub-team-id: 1" \
  -H "x-askhub-timestamp: <timestamp>" \
  -H "x-askhub-signature: <서명값>"

# 4. 인덱싱 완료 후 채팅하면 RAG 검색이 자동 적용됩니다
```

---

## API 엔드포인트 전체 목록

| Method | Path | 설명 | 인증 |
|--------|------|------|------|
| GET | `/health` | 프로세스 상태 확인 | 불필요 |
| GET | `/ready` | DB/설정 readiness 확인 | 불필요 |
| POST | `/v1/chat/sessions` | 채팅 세션 생성 | 필요 |
| GET | `/v1/chat/sessions` | 세션 목록 (커서 페이지네이션) | 필요 |
| GET | `/v1/chat/sessions/{session_id}` | 세션 상세 + 메시지 조회 | 필요 |
| POST | `/v1/chat/sessions/{session_id}/messages` | 메시지 전송 (동기) | 필요 |
| POST | `/v1/chat/sessions/{session_id}/messages/stream` | 메시지 전송 (SSE 스트리밍) | 필요 |
| POST | `/v1/files/upload` | 파일 업로드 (multipart/form-data) | 필요 |
| GET | `/v1/files` | 파일 목록 조회 | 필요 |
| GET | `/v1/files/{file_id}` | 파일 메타데이터 조회 | 필요 |
| GET | `/v1/files/{file_id}/download` | 파일 다운로드 (S3 presigned URL redirect) | 필요 |
| POST | `/v1/sources` | RAG 소스 등록 | 필요 |
| GET | `/v1/sources` | RAG 소스 목록 | 필요 |
| DELETE | `/v1/sources/{source_id}` | RAG 소스 삭제 | 필요 |
| POST | `/v1/ingestion-jobs` | 인덱싱 작업 생성 | 필요 |
| GET | `/v1/ingestion-jobs/{job_id}` | 인덱싱 작업 상태 조회 | 필요 |

---

## 환경 변수 레퍼런스

### 필수

| 변수 | 설명 | 예시 |
|------|------|------|
| `POSTGRES_HOST` | PostgreSQL 호스트 | `postgres` |
| `POSTGRES_DB` | 데이터베이스 이름 | `askhub` |
| `POSTGRES_USER` | DB 사용자 | `askhub` |
| `POSTGRES_PASSWORD` | DB 비밀번호 | - |
| `SERVICE_AUTH_SECRET` | HMAC 서명 시크릿 | 랜덤 문자열 |
| `AWS_ACCESS_KEY_ID` | AWS 액세스 키 | - |
| `AWS_SECRET_ACCESS_KEY` | AWS 시크릿 키 | - |
| `S3_BUCKET` | 파일 저장 S3 버킷 | `askhub-s3-xxx` |
| `S3_REGION` | S3 리전 | `ap-northeast-2` |

### 선택 (기본값 있음)

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `APP_ENV` | 실행 환경 | `local` |
| `LOG_LEVEL` | 로그 레벨 | `INFO` |
| `AWS_REGION` | Bedrock 리전 | `ap-southeast-2` |
| `BEDROCK_MODEL_ID` | LLM 모델 | `amazon.nova-lite-v1:0` |
| `BEDROCK_EMBED_MODEL_ID` | 임베딩 모델 | `amazon.titan-embed-text-v2:0` |
| `DB_SCHEMA` | ai-server DB 스키마 | `ai` |
| `RAG_TOP_K` | RAG 검색 상위 K | `5` |
| `RAG_SIMILARITY_THRESHOLD` | 유사도 임계값 | `0.3` |
| `RAG_MAX_CONTEXT_TOKENS` | RAG 컨텍스트 최대 토큰 | `4000` |
| `MAX_UPLOAD_BYTES` | 최대 업로드 크기 | `10485760` (10MB) |
| `MAX_FILES_PER_MESSAGE` | 메시지당 최대 첨부 | `5` |
| `ALLOWED_ORIGINS` | CORS 허용 출처 | `http://localhost:3000,http://localhost:5173` |
| `BACKEND_BASE_URL` | backend 서버 URL | `http://localhost:8080` |
| `ASKHUB_DOCKER_NETWORK` | Docker 네트워크 | `askhub-network` |

---

## Docker Compose 명령 요약

| 목적 | 명령 |
|------|------|
| DB 마이그레이션 | `docker compose --profile tools run --rm migrate` |
| API 서버 실행 | `docker compose up --build api` |
| Worker 실행 | `docker compose --profile worker up --build worker` |
| 테스트 실행 | `docker compose run --rm api-test pytest` |
| Bedrock 실 호출 테스트 | `docker compose run --rm -e RUN_LIVE_BEDROCK_TESTS=1 api-test pytest` |
| 린트 | `docker compose run --rm api-test ruff check .` |
| 수동 테스트 UI | `cd chatbot-test-ui && docker compose --env-file ..\.env up --build` |

> 이 프로젝트는 로컬 Python 환경에서의 직접 실행(`uvicorn`, `pytest`, `alembic`)을 지원하지 않습니다. 모든 실행은 Docker Compose를 통해 수행합니다.

---

## 프로젝트 구조

```
ai-server/
├── src/askhub_ai_server/
│   ├── main.py              # FastAPI 앱 팩토리 & 엔트리포인트
│   ├── worker.py            # Ingestion worker (RAG 인덱싱)
│   ├── api/routes/          # 라우터 (health, chat, files, sources, ingestion_jobs)
│   ├── core/                # 설정, DB, 인증, 미들웨어
│   ├── models/              # SQLAlchemy ORM 모델
│   ├── schemas/             # Pydantic 요청/응답 스키마
│   └── services/            # 비즈니스 로직 (LLM, RAG, 파일, 채팅)
├── alembic/                 # DB 마이그레이션
├── tests/                   # 테스트
├── docs/                    # 상세 문서
├── chatbot-test-ui/         # 로컬 수동 테스트 UI (Docker)
├── compose.yaml             # Docker Compose 설정
├── Dockerfile               # 멀티스테이지 빌드
└── .env.example             # 환경 변수 템플릿
```

---

## 추가 문서

- [Docker 로컬 실행 상세](docs/local-docker.md)
- [아키텍처](docs/architecture.md)
- [API 계약 상세](docs/api-contract.md)
- [개발 계획](docs/development-plan.md)
