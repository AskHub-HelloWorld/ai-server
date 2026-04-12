"""add s3 storage columns to user_files"""

import sqlalchemy as sa

from alembic import op
from askhub_ai_server.core.config import get_settings

revision = "202604120002"
down_revision = "202604120001"
branch_labels = None
depends_on = None

SCHEMA = get_settings().db_schema


def upgrade() -> None:
    op.add_column(
        "user_files",
        sa.Column("storage_provider", sa.String(length=20), nullable=False, server_default="local"),
        schema=SCHEMA,
    )
    op.add_column(
        "user_files",
        sa.Column("storage_bucket", sa.String(length=255), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "user_files",
        sa.Column("storage_key", sa.Text(), nullable=True),
        schema=SCHEMA,
    )
    op.alter_column("user_files", "storage_provider", server_default=None, schema=SCHEMA)


def downgrade() -> None:
    op.drop_column("user_files", "storage_key", schema=SCHEMA)
    op.drop_column("user_files", "storage_bucket", schema=SCHEMA)
    op.drop_column("user_files", "storage_provider", schema=SCHEMA)
