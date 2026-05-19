# AskHub AI Server API 계약

## 문서 상태

- 상태: 현재 구현 기준 계약
- 최종 수정: 2026-04-17
- 목적: backend/frontend와 ai-server 사이의 연동 계약을 정의한다.

## 연동 방향

MVP에서는 `frontend -> backend -> ai-server` 흐름을 기본으로 한다.

- frontend는 사용자 인증, 게시글 작성, 커뮤니티 화면을 backend API를 통해 처리한다.
- backend는 인증된 사용자와 팀 정보를 검증한 뒤 ai-server에 프록시 전달한다.
- ai-server는 채팅 세션/히스토리를 직접 DB에서 관리한다.
- ai-server는 RAG 검색(pgvector)과 Bedrock LLM 호출을 수행하여 답변을 생성한다.
- backend와 ai-server는 같은 PostgreSQL 인스턴스를 사용할 수 있지만, backend는 `backend` schema, ai-server는 `ai` schema만 소유한다.

주의: 브라우저가 `user_id`, `team_id`를 직접 ai-server에 넘기는 구조는 신뢰하지 않는다. ai-server는 backend가 서명한 service-to-service 헤더의 사용자/팀 context만 사용한다.

## 공통 DB 소유권

MVP는 단일 EC2의 PostgreSQL 16 + pgvector 인스턴스를 공유한다.

```text
database: askhub
schema: backend  -> backend 소유
schema: ai       -> ai-server 소유
```

권장 원칙:

- ai-server API는 `ai.chat_sessions`, `ai.messages`, `ai.user_files`, `ai.rag_sources`, `ai.document_chunks`, `ai.ingestion_jobs`만 write한다.
- backend API는 `backend.users`, `backend.teams`, `backend.posts`, `backend.comments`, `backend.points` 등 backend 도메인 테이블만 write한다.
- ai-server 요청의 `user_id`, `team_id`는 backend가 검증한 뒤 서명 헤더로 전달한 값을 저장한다.
- MVP에서는 ai-server 테이블에서 backend 테이블로 강한 FK를 걸지 않는다.
- 강한 FK 대신 backend 인증 context와 service-to-service 인증을 신뢰 경계로 사용한다.

## 공통 규칙

- 요청/응답 본문은 JSON을 사용한다.
- 기본 언어는 한국어다.
- 모든 시간은 ISO 8601 문자열을 사용한다.
- backend와 ai-server 사이에는 service-to-service 인증을 둔다.
- ai-server의 실행, 테스트, 린트, 마이그레이션은 `docs/local-docker.md`의 Docker Compose 명령을 기준으로 한다.

## Service-to-service 인증

도메인 API는 아래 헤더를 요구한다. `GET /health`, `GET /ready`는 예외다.

- `X-AskHub-User-Id`: backend가 검증한 사용자 ID.
- `X-AskHub-Team-Id`: backend가 검증한 팀 ID. 팀 context가 없는 요청에서는 생략 가능하다.
- `X-AskHub-Timestamp`: Unix epoch seconds.
- `X-AskHub-Signature`: `SERVICE_AUTH_SECRET`으로 생성한 HMAC-SHA256 hex digest.

서명 payload는 아래 줄바꿈 구분 문자열이다.

```text
{timestamp}
{HTTP_METHOD}
{request_path}
{query_string}
{user_id}
{team_id_or_empty_string}
```

---

## 구현된 API

### `GET /health`

ai-server 프로세스 상태를 확인한다.

응답 예시:

```json
{
  "service": "AskHub AI Server",
  "environment": "local",
  "version": "0.1.0",
  "status": "ok"
}
```

### `GET /ready`

DB 연결, service auth 설정, Bedrock 필수 설정을 확인한다.

## 세션 기반 채팅 API

ai-server가 `ai.chat_sessions`, `ai.messages` 테이블을 사용해 세션과 메시지 히스토리를 직접 관리한다. 공개 채팅 API는 세션 기반 endpoint만 사용한다.

제거된 legacy endpoint:

- `POST /v1/chat`
- `POST /v1/chat/stream`

이 endpoint들은 backend가 히스토리를 전달하는 과거 구조에 맞춰져 있었기 때문에 제거했다. 신규 연동은 아래 API만 사용한다.

### `POST /v1/chat/sessions`

새 채팅 세션을 생성한다.

요청 예시:

```json
{}
```

응답 예시:

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": 1,
  "team_id": 10,
  "title": null,
  "created_at": "2026-04-07T12:00:00Z"
}
```

### `GET /v1/chat/sessions`

사용자의 채팅 세션 목록을 조회한다.

쿼리 파라미터:

- `team_id` (선택): 헤더의 팀 context와 일치해야 한다.

응답 예시:

```json
{
  "sessions": [
    {
      "session_id": "550e8400-...",
      "title": "배포 파이프라인 질문",
      "created_at": "2026-04-07T12:00:00Z",
      "updated_at": "2026-04-07T12:05:00Z"
    }
  ]
}
```

### `GET /v1/chat/sessions/{session_id}`

세션 상세 정보와 메시지 히스토리를 조회한다.

응답 예시:

```json
{
  "session_id": "550e8400-...",
  "user_id": 1,
  "team_id": 10,
  "title": "배포 파이프라인 질문",
  "messages": [
    {"id": "msg-1", "role": "user", "content": "배포는 어떻게 하나요?", "created_at": "..."},
    {"id": "msg-2", "role": "assistant", "content": "배포 파이프라인은...", "answerable": true, "citations": [], "created_at": "..."}
  ]
}
```

### `POST /v1/chat/sessions/{session_id}/messages`

세션에 메시지를 전송하고 AI 응답을 받는다 (non-streaming).

요청 예시:

```json
{
  "message": "배포 파이프라인은 어디에 있나요?",
  "file_ids": []
}
```

응답 예시:

```json
{
  "answer": "배포 파이프라인은 .github/workflows/deploy.yml에 정의되어 있습니다.",
  "answerable": true,
  "citations": [
    {
      "title": "deploy.yml",
      "source_type": "repository",
      "repo": "backend",
      "path": ".github/workflows/deploy.yml",
      "commit_sha": "abc1234",
      "line_start": 1,
      "line_end": 30
    }
  ],
  "suggested_post": null
}
```

### `POST /v1/chat/sessions/{session_id}/messages/stream`

세션에 메시지를 전송하고 SSE 스트리밍으로 AI 응답을 받는다.

요청 형식은 `POST /v1/chat/sessions/{session_id}/messages`와 동일하다.

SSE 이벤트:

| event | data | 설명 |
|-------|------|------|
| `metadata` | `{"session_id": "...", "user_message_id": "..."}` | 세션/사용자 메시지 정보 |
| `token` | `{"delta": "텍스트 조각"}` | 토큰 단위 응답 |
| `done` | `{"assistant_message_id": "...", "full_response": "...", "answerable": true}` | assistant 메시지 저장 후 스트리밍 완료 |
| `error` | `{"message": "에러 내용"}` | 오류 발생 시 |

ai-server는 streaming 시작 전에 user 메시지를 저장하고, `done` 이벤트 직전에 assistant 응답을 DB에 저장한다.

현재 구현 범위:

- user 메시지 저장
- DB에서 이전 history 조회
- Bedrock LLM 호출
- assistant 메시지 저장
- `file_ids`로 전달한 소유 파일 중 텍스트는 UTF-8 context로, PNG/JPEG 이미지는 Bedrock image content block으로 LLM 입력에 반영한다.
- 그 외 binary 파일은 업로드/첨부 자체를 차단하지 않고 파일 metadata를 LLM context에 전달한다. 원문 추출은 RAG ingestion 단계에서 별도 parser/OCR로 확장한다.

## RAG/인덱싱 API

### `POST /v1/sources`

문서 또는 레포지토리 소스 메타데이터를 `ai.rag_sources`에 등록한다. 팀 ID는 service-to-service 헤더의 팀 context를 사용한다.

레포지토리 소스 요청 예시:

```json
{
  "source_type": "repository",
  "name": "backend",
  "repo_url": "https://github.com/AskHub-HelloWorld/backend.git",
  "default_branch": "main"
}
```

문서 소스 요청 예시:

```json
{
  "source_type": "document",
  "name": "guide.pdf",
  "file_id": "660e8400-e29b-41d4-a716-446655440000"
}
```

문서 소스의 `file_id`는 `POST /v1/files/upload` 응답의 `id`를 사용한다. 이 값은 파일 메타데이터 ID이며, RAG 소스 삭제에 사용하는 `source_id`가 아니다. RAG 소스 삭제와 인덱싱 작업 생성에는 `POST /v1/sources` 응답의 `source_id`를 사용한다.

### `POST /v1/ingestion-jobs`

등록된 source를 기준으로 `ai.ingestion_jobs`에 `queued` 작업을 생성한다.

### `GET /v1/ingestion-jobs/{job_id}`

인덱싱 작업 상태를 조회한다.

## 파일 API

### `POST /v1/files/upload`

파일을 업로드한다. multipart/form-data를 사용한다.

요청 필드:

- `file` (필수): 업로드할 파일.
- `session_id` (선택): 채팅 세션 ID. 값이 있으면 헤더 context의 소유 세션이어야 한다.
- `purpose` (선택): `chat_attachment` (기본값) 또는 `rag_source`.

응답 예시:

```json
{
  "id": "660e8400-e29b-41d4-a716-446655440000",
  "user_id": 1,
  "team_id": 10,
  "session_id": null,
  "filename": "error.log",
  "content_type": "text/plain",
  "file_size": 2048,
  "purpose": "chat_attachment",
  "created_at": "2026-04-12T07:00:00Z"
}
```

응답의 `id`는 `ai.user_files.id`에 해당하는 `file_id`다. `purpose=rag_source`로 업로드하더라도 이 API는 파일만 저장하며 `ai.rag_sources` row를 만들지 않는다. 문서를 RAG 소스로 사용하려면 이 `id`를 `POST /v1/sources`의 `file_id`로 전달하고, 그 응답의 `source_id`를 별도로 저장해야 한다.

내부 `storage_path`는 응답하지 않는다. `purpose=chat_attachment`인 파일은 채팅 메시지 전송 시 `file_ids`에 포함하여 LLM context로 활용한다. 업로드 단계에서는 content type으로 차단하지 않고, 채팅 단계에서 텍스트/이미지/기타 binary 파일을 분기 처리한다.

### `GET /v1/files`

헤더 context의 사용자가 업로드한 파일 metadata 목록을 조회한다.

### `GET /v1/files/{file_id}`

헤더 context의 사용자가 소유한 파일 metadata를 조회한다.

### `GET /v1/files/{file_id}/download`

권한 검증 후 S3 presigned URL로 302 리다이렉트한다.

- 소유자 본인 파일: 직접 다운로드 가능.
- 타인 파일: `purpose=rag_source`이고 같은 팀인 경우에만 다운로드 가능.

## RAG 소스 API (추가)

### `GET /v1/sources`

헤더 context의 팀에 등록된 RAG 소스 목록을 조회한다. 각 소스의 `chunk_count`도 함께 반환한다.

팀 context가 없으면 400을 반환한다.

응답 예시:

```json
{
  "sources": [
    {
      "source_id": "770e8400-...",
      "source_type": "repository",
      "name": "github.com/AskHub-HelloWorld/backend",
      "team_id": 10,
      "status": "ready",
      "status_label": "✓ 사용 가능",
      "type_label": "레포",
      "repo_url": "https://github.com/AskHub-HelloWorld/backend.git",
      "default_branch": "main",
      "summary": "Spring Boot 기반 백엔드 서비스...",
      "chunk_count": 142,
      "created_at": "2026-04-13T10:00:00Z"
    }
  ]
}
```

### `DELETE /v1/sources/{source_id}`

RAG 소스를 삭제한다. 연결된 `ingestion_jobs`와 `document_chunks`도 CASCADE 삭제된다.

`source_id`는 `POST /v1/sources` 또는 `GET /v1/sources` 응답의 `source_id`다. `POST /v1/files/upload` 응답의 `id`는 `file_id`이므로 이 경로에 넣으면 `source not found`가 반환된다.

팀 context와 소스의 `team_id`가 일치해야 한다. 불일치 시 404를 반환한다.

성공 시 204 No Content를 반환한다.

---

## backend에 필요한 API 후보

backend 구현 전 협의가 필요한 API다.

- `POST /api/auth/login`: 로그인 → JWT 발급.
- `GET /api/me`: 현재 로그인 사용자와 소속 팀 목록 조회.
- `POST /api/posts`: AI가 답변하지 못한 질문을 커뮤니티 게시글로 생성.
- `GET /api/posts`: 커뮤니티 게시글 목록 조회.
- `POST /api/posts/{id}/comments`: 게시글에 댓글 작성.

ai-server는 게시글을 직접 저장하지 않고, `suggested_post` 초안을 반환하는 역할까지만 담당한다.

## 미결정 사항

- SSE 스트리밍을 backend가 프록시할지, 별도 경로로 처리할지.
- 팀 간 RAG 소스 공유 정책.
