# Docker 로컬 실행

이 프로젝트는 실행, 테스트, 린트, 마이그레이션을 모두 Docker Compose 안에서 수행합니다. 로컬 Python 환경에 패키지를 설치하거나 로컬에서 `pytest`, `ruff`, `uvicorn`, `alembic`을 직접 실행하지 않습니다.

## 전제 조건

- Docker Desktop이 실행 중이어야 합니다.
- backend 레포의 PostgreSQL/pgvector 컨테이너가 같은 Docker network에서 떠 있어야 합니다.
- `ai-server/.env`는 `ai-server/.env.example`을 기준으로 생성합니다.
- `POSTGRES_*`, `ASKHUB_DOCKER_NETWORK`, `DB_SCHEMA`, `TEST_DB_SCHEMA`, `SERVICE_AUTH_SECRET`, Bedrock/S3 설정이 필요합니다.

## 1. backend PostgreSQL 실행

backend 레포에서 PostgreSQL을 먼저 실행합니다.

```bash
docker compose up -d postgres
```

`ASKHUB_DOCKER_NETWORK` 값은 backend compose가 사용하는 Docker network 이름과 같아야 합니다.

## 2. ai-server 마이그레이션

ai-server 레포에서 `ai` schema migration을 적용합니다.

```bash
docker compose --profile tools run --rm migrate
```

## 3. API 실행

```bash
docker compose up --build api
```

Swagger UI는 브라우저에서 확인합니다.

```text
http://localhost:8000/docs
```

컨테이너 내부에서 health/readiness를 확인하려면 아래 명령을 사용합니다.

```bash
docker compose exec api python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/health').read().decode())"
docker compose exec api python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/ready').read().decode())"
```

## 4. Worker 실행

RAG source ingestion을 처리하려면 별도 터미널에서 worker를 실행합니다.

```bash
docker compose --profile worker up --build worker
```

worker는 `ingestion_jobs`의 `queued` 작업을 claim하고, repository/document source를 chunking 및 embedding 후 `document_chunks`에 저장합니다.

## 5. 테스트

기본 테스트:

```bash
docker compose run --rm api-test pytest
```

Bedrock 실 호출을 포함한 테스트:

```bash
docker compose run --rm -e RUN_LIVE_BEDROCK_TESTS=1 api-test pytest
```

특정 테스트 파일:

```bash
docker compose run --rm api-test pytest tests/test_chat_sessions.py
```

## 6. 린트

```bash
docker compose run --rm api-test ruff check .
```

## 7. 수동 테스트 UI

`chatbot-test-ui`는 로컬 수동 테스트용 Docker UI입니다. API 컨테이너를 먼저 실행한 뒤 별도 터미널에서 실행합니다.

```bash
cd chatbot-test-ui
docker compose --env-file ..\.env up --build
```

브라우저에서 아래 주소를 엽니다.

```text
http://localhost:5173
```

## 공식 명령 요약

| 목적 | 명령 |
|------|------|
| DB migration | `docker compose --profile tools run --rm migrate` |
| API 실행 | `docker compose up --build api` |
| Worker 실행 | `docker compose --profile worker up --build worker` |
| 테스트 | `docker compose run --rm api-test pytest` |
| Live Bedrock 테스트 | `docker compose run --rm -e RUN_LIVE_BEDROCK_TESTS=1 api-test pytest` |
| 린트 | `docker compose run --rm api-test ruff check .` |

## 지원하지 않는 실행 방식

아래 방식은 공식 개발 경로가 아닙니다.

```bash
python -m pytest
python -m ruff check .
uvicorn askhub_ai_server.main:app --reload
alembic upgrade head
```
