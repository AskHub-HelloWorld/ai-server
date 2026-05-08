"""add rag_context_summary to messages"""

import sqlalchemy as sa

from alembic import op
from askhub_ai_server.core.config import get_settings

revision = "202605070001"
down_revision = "202604180001"
branch_labels = None
depends_on = None

SCHEMA = get_settings().db_schema


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("rag_context_summary", sa.Text(), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("messages", "rag_context_summary", schema=SCHEMA)
