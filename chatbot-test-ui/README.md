# AskHub AI Chat Test UI

`ai-server`의 FastAPI 채팅 API를 브라우저에서 테스트하는 Docker 기반 화면입니다.
브라우저는 같은 origin의 dev proxy를 호출하고, dev proxy가 `SERVICE_AUTH_SECRET`으로 HMAC 헤더를 생성해 ai-server로 전달합니다.

## 실행

FastAPI를 먼저 실행합니다.

```bash
cd C:\ITStudy\AskHub-HelloWorld\ai-server
docker compose up --build api
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
POST /v1/chat/sessions/{session_id}/messages/stream
```

브라우저는 위 API를 직접 호출하지 않고 `/api/*` dev proxy 경로로 호출합니다. 스트리밍은 `POST` 요청이 필요하므로 `EventSource`가 아니라 `fetch()`의 `ReadableStream`으로 SSE 이벤트를 파싱합니다.
