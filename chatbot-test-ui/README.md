# AskHub AI Chat Test UI

`ai-server`의 FastAPI 채팅 API를 브라우저에서 테스트하는 Docker 기반 화면입니다.
브라우저는 같은 origin의 dev proxy를 호출하고, dev proxy가 `SERVICE_AUTH_SECRET`으로 HMAC 헤더를 생성해 ai-server로 전달합니다.

이 UI도 Docker Compose로만 실행합니다. 로컬 Python으로 `server.py`를 직접 실행하지 않습니다.

## 실행

ai-server API 컨테이너를 먼저 실행합니다.

```bash
cd C:\ITStudy\AskHub-HelloWorld\ai-server
docker compose --profile tools run --rm migrate
docker compose up --build api
```

RAG 소스 인덱싱을 테스트하려면 worker도 실행합니다.

```bash
cd C:\ITStudy\AskHub-HelloWorld\ai-server
docker compose --profile worker up --build worker
```

별도 터미널에서 테스트 UI 컨테이너를 실행합니다.

```bash
cd C:\ITStudy\AskHub-HelloWorld\ai-server\chatbot-test-ui
docker compose --env-file ..\.env up --build
```

브라우저에서 엽니다.

```text
http://localhost:5173
```

다른 포트를 사용해야 하면 아래처럼 실행합니다.

```bash
set CHATBOT_TEST_UI_PORT=5174
docker compose --env-file ..\.env up --build
```

WSL/bash에서는 아래처럼 실행합니다.

```bash
CHATBOT_TEST_UI_PORT=5174 docker compose --env-file ../.env up --build
```

ai-server가 `http://localhost:8000`이 아닌 곳에 있으면 proxy 대상 URL을 바꿉니다.

```bash
set AI_SERVER_BASE_URL=http://host.docker.internal:8000
docker compose --env-file ..\.env up --build
```

WSL/bash에서는 아래처럼 실행합니다.

```bash
AI_SERVER_BASE_URL=http://host.docker.internal:8000 docker compose --env-file ../.env up --build
```

## 사용 값

화면에서 아래 값을 입력합니다.

```text
User ID: 테스트 사용자 ID
Team ID: 테스트 팀 ID 또는 빈 값
```

`SERVICE_AUTH_SECRET`은 `--env-file ../.env`로 Compose 변수에 주입되고, 테스트 UI 컨테이너에는 해당 값만 명시적으로 전달됩니다. 화면에는 노출하지 않습니다.
이 화면은 로컬 테스트 전용입니다.

## 사용 API

```text
POST /v1/chat/sessions
GET  /v1/chat/sessions
GET  /v1/chat/sessions/{session_id}
POST /v1/files/upload
GET  /v1/files/{file_id}/download
GET  /v1/sources
POST /v1/sources
DELETE /v1/sources/{source_id}
POST /v1/ingestion-jobs
GET  /v1/ingestion-jobs/{job_id}
POST /v1/chat/sessions/{session_id}/messages/stream
```

브라우저는 위 API를 직접 호출하지 않고 `/api/*` dev proxy 경로로 호출합니다. 스트리밍은 `POST` 요청이 필요하므로 `EventSource`가 아니라 `fetch()`의 `ReadableStream`으로 SSE 이벤트를 파싱합니다.

## RAG 소스 테스트

1. 화면 왼쪽 하단의 `AH` 설정 패널을 엽니다.
2. `User ID`와 `Team ID`를 입력합니다. RAG 소스는 Team ID가 필요합니다.
3. `RAG 소스`에서 PDF/Word/text 파일을 선택하고 `소스로 추가하고 인덱싱`을 누릅니다.
4. 상태가 `인덱싱 완료`가 될 때까지 기다립니다.
5. 채팅 입력창에는 파일을 다시 첨부하지 않고 질문만 보냅니다.

예시 질문:

```text
베이즈 정리가 무엇인가? 실제 예시를 들어 설명해라
```

답변 본문에는 `[1]`, `[2]` 인라인 출처가 붙고, 답변 아래 citation 링크는 `/api/v1/files/{file_id}/download`를 통해 원본 문서를 엽니다. raw `s3://` 경로는 화면에 표시하지 않습니다.
