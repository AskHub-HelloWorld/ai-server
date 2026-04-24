"""add contextual search metadata to document_chunks"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from askhub_ai_server.core.config import get_settings

revision = "202604180001"
down_revision = "202604150001"
branch_labels = None
depends_on = None

SCHEMA = get_settings().db_schema


def upgrade() -> None:
    op.add_column(
        "document_chunks",
        sa.Column("embedding_text", sa.Text(), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "document_chunks",
        sa.Column("search_text", sa.Text(), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "document_chunks",
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        schema=SCHEMA,
    )
    op.execute(
        f"UPDATE {SCHEMA}.document_chunks "
        "SET embedding_text = content, search_text = content "
        "WHERE embedding_text IS NULL OR search_text IS NULL"
    )
    op.execute(
        f"CREATE INDEX ix_ai_document_chunks_search_text_tsv "
        f"ON {SCHEMA}.document_chunks "
        "USING gin (to_tsvector('simple', coalesce(search_text, content)))"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {SCHEMA}.ix_ai_document_chunks_search_text_tsv")
    op.drop_column("document_chunks", "metadata_json", schema=SCHEMA)
    op.drop_column("document_chunks", "search_text", schema=SCHEMA)
    op.drop_column("document_chunks", "embedding_text", schema=SCHEMA)
