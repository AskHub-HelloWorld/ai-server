"""create user_files table"""

import os

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "202604080001"
down_revision = "202604070001"
branch_labels = None
depends_on = None

SCHEMA = os.getenv("DB_SCHEMA", "ai")


def upgrade() -> None:
    op.create_table(
        "user_files",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("team_id", sa.BigInteger(), nullable=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("filename", sa.String(length=500), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("purpose", sa.String(length=20), nullable=False, server_default="chat_attachment"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.CheckConstraint(
            "purpose IN ('chat_attachment', 'rag_source')",
            name="ck_user_files_purpose",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            [f"{SCHEMA}.chat_sessions.id"],
            name="fk_user_files_session_id_chat_sessions",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_files"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_ai_user_files_user_id",
        "user_files",
        ["user_id"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index("ix_ai_user_files_user_id", table_name="user_files", schema=SCHEMA)
    op.drop_table("user_files", schema=SCHEMA)
