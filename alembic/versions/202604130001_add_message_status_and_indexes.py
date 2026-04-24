"""add message status/failure_reason and session indexes

Adds explicit message state tracking (pending → completed | failed)
and indexes to support cursor-based pagination on chat_sessions.
"""

import sqlalchemy as sa

from alembic import op
from askhub_ai_server.core.config import get_settings

revision = "202604130001"
down_revision = "202604120002"
branch_labels = None
depends_on = None

SCHEMA = get_settings().db_schema


def upgrade() -> None:
    # --- Message: status column ---
    op.add_column(
        "messages",
        sa.Column(
            "status",
            sa.String(length=10),
            nullable=False,
            server_default="completed",
        ),
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_messages_status",
        "messages",
        "status IN ('pending', 'completed', 'failed')",
        schema=SCHEMA,
    )

    # --- Message: failure_reason column ---
    op.add_column(
        "messages",
        sa.Column("failure_reason", sa.Text(), nullable=True),
        schema=SCHEMA,
    )

    # --- ChatSession: indexes for cursor-based pagination ---
    op.create_index(
        "ix_ai_chat_sessions_user_updated",
        "chat_sessions",
        ["user_id", "updated_at"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_ai_chat_sessions_user_team_updated",
        "chat_sessions",
        ["user_id", "team_id", "updated_at"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ai_chat_sessions_user_team_updated",
        table_name="chat_sessions",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_ai_chat_sessions_user_updated",
        table_name="chat_sessions",
        schema=SCHEMA,
    )
    op.drop_constraint("ck_messages_status", "messages", schema=SCHEMA)
    op.drop_column("messages", "failure_reason", schema=SCHEMA)
    op.drop_column("messages", "status", schema=SCHEMA)
