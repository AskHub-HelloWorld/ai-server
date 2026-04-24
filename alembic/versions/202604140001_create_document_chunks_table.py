"""create document_chunks table for RAG vector storage"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from askhub_ai_server.core.config import get_settings

revision = "202604140001"
down_revision = "202604130001"
branch_labels = None
depends_on = None

SCHEMA = get_settings().db_schema


def upgrade() -> None:
    op.create_table(
        "document_chunks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("team_id", sa.BigInteger(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("file_type", sa.String(length=50), nullable=True),
        sa.Column("line_start", sa.Integer(), nullable=True),
        sa.Column("line_end", sa.Integer(), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("commit_sha", sa.String(length=40), nullable=True),
        sa.Column("repo_url", sa.Text(), nullable=True),
        # embedding column added via raw SQL below (pgvector type)
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            [f"{SCHEMA}.rag_sources.id"],
            name="fk_document_chunks_source_id_rag_sources",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            [f"{SCHEMA}.ingestion_jobs.id"],
            name="fk_document_chunks_job_id_ingestion_jobs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_chunks"),
        schema=SCHEMA,
    )

    # Regular indexes for filtered queries
    op.create_index(
        "ix_ai_document_chunks_source_id",
        "document_chunks",
        ["source_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_ai_document_chunks_job_id",
        "document_chunks",
        ["job_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_ai_document_chunks_team_id",
        "document_chunks",
        ["team_id"],
        schema=SCHEMA,
    )

    # Add the vector column using raw SQL (pgvector type not directly supported by SA Column)
    op.execute(
        f"ALTER TABLE {SCHEMA}.document_chunks "
        "ADD COLUMN embedding vector(1024) NOT NULL"
    )

    # HNSW index for cosine similarity search
    op.execute(
        f"CREATE INDEX ix_ai_document_chunks_embedding "
        f"ON {SCHEMA}.document_chunks "
        f"USING hnsw (embedding vector_cosine_ops) "
        f"WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {SCHEMA}.ix_ai_document_chunks_embedding")
    op.drop_index("ix_ai_document_chunks_team_id", table_name="document_chunks", schema=SCHEMA)
    op.drop_index("ix_ai_document_chunks_job_id", table_name="document_chunks", schema=SCHEMA)
    op.drop_index("ix_ai_document_chunks_source_id", table_name="document_chunks", schema=SCHEMA)
    op.drop_table("document_chunks", schema=SCHEMA)
