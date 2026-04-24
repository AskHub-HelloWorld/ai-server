from __future__ import annotations

import os
import time
from collections.abc import Iterator

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from alembic import command
from askhub_ai_server.core.config import get_settings
from askhub_ai_server.core.database import SessionLocal, engine
from askhub_ai_server.core.security import (
    SIGNATURE_HEADER,
    TEAM_ID_HEADER,
    TIMESTAMP_HEADER,
    USER_ID_HEADER,
    build_service_signature,
)
from askhub_ai_server.main import create_app

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "live_bedrock: requires real Bedrock access")


@pytest.fixture(scope="session", autouse=True)
def migrated_test_schema() -> Iterator[None]:
    settings = get_settings()
    if settings.app_env != "test" or "test" not in settings.db_schema.lower():
        pytest.exit("Refusing to run DB tests outside a test app_env and test schema")
    if not settings.service_auth_secret:
        pytest.exit("SERVICE_AUTH_SECRET is required for integration tests")

    command.upgrade(Config(os.path.join(ROOT_DIR, "alembic.ini")), "head")
    yield


@pytest.fixture(autouse=True)
def clean_tables(migrated_test_schema: None) -> Iterator[None]:
    settings = get_settings()
    tables = [
        "document_chunks",
        "ingestion_jobs",
        "rag_sources",
        "user_files",
        "messages",
        "chat_sessions",
    ]
    with engine.begin() as connection:
        for table in tables:
            connection.execute(text(f'DELETE FROM "{settings.db_schema}".{table}'))

    yield

    with engine.begin() as connection:
        for table in tables:
            connection.execute(text(f'DELETE FROM "{settings.db_schema}".{table}'))


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture()
def db_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def auth_headers(
    method: str,
    path: str,
    *,
    query: str = "",
    user_id: int = 1,
    team_id: int | None = 10,
) -> dict[str, str]:
    settings = get_settings()
    timestamp, signature = build_service_signature(
        secret=settings.service_auth_secret,
        method=method,
        path=path,
        query=query,
        user_id=user_id,
        team_id=team_id,
        timestamp=int(time.time()),
    )
    headers = {
        USER_ID_HEADER: str(user_id),
        TIMESTAMP_HEADER: timestamp,
        SIGNATURE_HEADER: signature,
    }
    if team_id is not None:
        headers[TEAM_ID_HEADER] = str(team_id)
    return headers


def live_bedrock_enabled() -> bool:
    return os.getenv("RUN_LIVE_BEDROCK_TESTS") == "1"


