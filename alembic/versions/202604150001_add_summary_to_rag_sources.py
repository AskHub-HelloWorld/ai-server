"""add summary column to rag_sources for auto-generated source summaries"""

import sqlalchemy as sa

from alembic import op
from askhub_ai_server.core.config import get_settings

revision = "202604150001"
down_revision = "202604140003"
branch_labels = None
depends_on = None

SCHEMA = get_settings().db_schema


def upgrade() -> None:
    op.add_column(
        "rag_sources",
        sa.Column("summary", sa.Text(), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("rag_sources", "summary", schema=SCHEMA)
