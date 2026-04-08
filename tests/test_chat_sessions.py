from pathlib import Path

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text

from alembic import command
from askhub_ai_server.api.routes import chat as chat_routes
from askhub_ai_server.core.config import get_settings
from askhub_ai_server.core.database import engine
from askhub_ai_server.main import create_app
from askhub_ai_server.schemas.chat import ChatRequest

ROOT_DIR = Path(__file__).resolve().parents[1]


class StubLLMService:
    def converse(self, request: ChatRequest) -> str:
        return f"응답: {request.message} / history={len(request.history)}"

    def converse_stream(self, request: ChatRequest):
        yield "응답: "
        yield request.message


@pytest.fixture()
def clean_chat_tables():
    command.upgrade(Config(str(ROOT_DIR / "alembic.ini")), "head")
    schema = get_settings().db_schema

    with engine.begin() as connection:
        connection.execute(text(f'DELETE FROM "{schema}".messages'))
        connection.execute(text(f'DELETE FROM "{schema}".chat_sessions'))

    yield

    with engine.begin() as connection:
        connection.execute(text(f'DELETE FROM "{schema}".messages'))
        connection.execute(text(f'DELETE FROM "{schema}".chat_sessions'))


@pytest.fixture()
def client(monkeypatch, clean_chat_tables) -> TestClient:
    monkeypatch.setattr(chat_routes, "get_llm_service", lambda: StubLLMService())
    return TestClient(create_app())


def test_create_list_and_get_chat_session(client: TestClient) -> None:
    create_response = client.post("/v1/chat/sessions", json={"user_id": 1, "team_id": 10})

    assert create_response.status_code == 201
    session = create_response.json()
    assert session["user_id"] == 1
    assert session["team_id"] == 10
    assert session["title"] is None

    list_response = client.get("/v1/chat/sessions", params={"user_id": 1})

    assert list_response.status_code == 200
    assert len(list_response.json()["sessions"]) == 1

    detail_response = client.get(f"/v1/chat/sessions/{session['session_id']}")

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["session_id"] == session["session_id"]
    assert detail["messages"] == []


def test_create_session_message_persists_user_and_assistant_messages(
    client: TestClient,
) -> None:
    session = client.post("/v1/chat/sessions", json={"user_id": 1, "team_id": 10}).json()

    message_response = client.post(
        f"/v1/chat/sessions/{session['session_id']}/messages",
        json={"message": "배포 파이프라인은 어디에 있나요?", "file_ids": []},
    )

    assert message_response.status_code == 200
    message_body = message_response.json()
    assert message_body["answerable"] is True
    assert message_body["answer"].startswith("응답:")

    detail_response = client.get(f"/v1/chat/sessions/{session['session_id']}")

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["title"] == "배포 파이프라인은 어디에 있나요?"
    assert [message["role"] for message in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][0]["content"] == "배포 파이프라인은 어디에 있나요?"
    assert detail["messages"][1]["content"].startswith("응답:")


def test_stream_session_message_persists_assistant_message(client: TestClient) -> None:
    session = client.post("/v1/chat/sessions", json={"user_id": 1, "team_id": 10}).json()

    with client.stream(
        "POST",
        f"/v1/chat/sessions/{session['session_id']}/messages/stream",
        json={"message": "로그 파일을 분석해줘", "file_ids": []},
    ) as response:
        body = response.read().decode()

    assert response.status_code == 200
    assert "event: metadata" in body
    assert "event: token" in body
    assert "event: done" in body
    assert "로그 파일을 분석해줘" in body

    detail_response = client.get(f"/v1/chat/sessions/{session['session_id']}")

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert [message["role"] for message in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][1]["content"] == "응답: 로그 파일을 분석해줘"

