"""add file_id to rag_sources for S3-backed document sources"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from askhub_ai_server.core.config import get_settings

revision = "202604140003"
down_revision = "202604140002"
branch_labels = None
depends_on = None

SCHEMA = get_settings().db_schema


def upgrade() -> None:
    op.add_column(
        "rag_sources",
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_ai_rag_sources_file_id",
        "rag_sources",
        ["file_id"],
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_rag_sources_file_id_user_files",
        "rag_sources",
        "user_files",
        ["file_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_rag_sources_file_id_user_files",
        "rag_sources",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.drop_index("ix_ai_rag_sources_file_id", table_name="rag_sources", schema=SCHEMA)
    op.drop_column("rag_sources", "file_id", schema=SCHEMA)
