from askhub_ai_server.core.config import get_settings
from askhub_ai_server.core.database import Base
from askhub_ai_server.models import ChatSession, Message


def test_ai_schema_metadata_contains_chat_tables() -> None:
    settings = get_settings()

    assert Base.metadata.schema == settings.db_schema
    assert ChatSession.__tablename__ == "chat_sessions"
    assert Message.__tablename__ == "messages"
    assert f"{settings.db_schema}.chat_sessions" in Base.metadata.tables
    assert f"{settings.db_schema}.messages" in Base.metadata.tables

