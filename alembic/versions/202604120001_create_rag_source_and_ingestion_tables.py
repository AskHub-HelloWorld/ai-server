"""create rag source and ingestion job tables"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from askhub_ai_server.core.config import get_settings

revision = "202604120001"
down_revision = "202604080001"
branch_labels = None
depends_on = None

SCHEMA = get_settings().db_schema


def upgrade() -> None:
    op.create_table(
        "rag_sources",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("source_type", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("team_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="registered"),
        sa.Column("repo_url", sa.Text(), nullable=True),
        sa.Column("default_branch", sa.String(length=200), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.CheckConstraint(
            "source_type IN ('repository', 'document')",
            name="ck_rag_sources_source_type",
        ),
        sa.CheckConstraint(
            "status IN ('registered')",
            name="ck_rag_sources_status",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_rag_sources"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_ai_rag_sources_team_id",
        "rag_sources",
        ["team_id"],
        schema=SCHEMA,
    )

    op.create_table(
        "ingestion_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("indexed_object_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.CheckConstraint(
            "mode IN ('full', 'incremental')",
            name="ck_ingestion_jobs_mode",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_ingestion_jobs_status",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            [f"{SCHEMA}.rag_sources.id"],
            name="fk_ingestion_jobs_source_id_rag_sources",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ingestion_jobs"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_ai_ingestion_jobs_source_id",
        "ingestion_jobs",
        ["source_id"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index("ix_ai_ingestion_jobs_source_id", table_name="ingestion_jobs", schema=SCHEMA)
    op.drop_table("ingestion_jobs", schema=SCHEMA)
    op.drop_index("ix_ai_rag_sources_team_id", table_name="rag_sources", schema=SCHEMA)
    op.drop_table("rag_sources", schema=SCHEMA)
