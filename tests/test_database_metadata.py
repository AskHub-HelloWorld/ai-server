from askhub_ai_server.core.config import get_settings
from askhub_ai_server.core.database import Base
from askhub_ai_server.models import ChatSession, IngestionJob, Message, RagSource, UserFile


def test_ai_schema_metadata_contains_chat_tables() -> None:
    settings = get_settings()

    assert Base.metadata.schema == settings.db_schema
    assert ChatSession.__tablename__ == "chat_sessions"
    assert Message.__tablename__ == "messages"
    assert UserFile.__tablename__ == "user_files"
    assert RagSource.__tablename__ == "rag_sources"
    assert IngestionJob.__tablename__ == "ingestion_jobs"
    assert f"{settings.db_schema}.chat_sessions" in Base.metadata.tables
    assert f"{settings.db_schema}.messages" in Base.metadata.tables
    assert f"{settings.db_schema}.user_files" in Base.metadata.tables
    assert f"{settings.db_schema}.rag_sources" in Base.metadata.tables
    assert f"{settings.db_schema}.ingestion_jobs" in Base.metadata.tables
