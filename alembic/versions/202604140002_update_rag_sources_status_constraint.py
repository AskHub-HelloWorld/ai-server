"""update rag_sources status check constraint to allow indexing/ready/error"""

from alembic import op
from askhub_ai_server.core.config import get_settings

revision = "202604140002"
down_revision = "202604140001"
branch_labels = None
depends_on = None

SCHEMA = get_settings().db_schema

# SQLAlchemy naming convention doubles the prefix:
#   ck_%(table_name)s_%(constraint_name)s  →  ck_rag_sources_ck_rag_sources_status
CONSTRAINT_DB_NAME = "ck_rag_sources_ck_rag_sources_status"


def upgrade() -> None:
    op.execute(
        f'ALTER TABLE "{SCHEMA}".rag_sources DROP CONSTRAINT IF EXISTS "{CONSTRAINT_DB_NAME}"'
    )
    # Also try the non-prefixed name in case of older schemas
    op.execute(
        f'ALTER TABLE "{SCHEMA}".rag_sources DROP CONSTRAINT IF EXISTS "ck_rag_sources_status"'
    )
    op.execute(
        f"ALTER TABLE \"{SCHEMA}\".rag_sources "
        f"ADD CONSTRAINT \"{CONSTRAINT_DB_NAME}\" "
        f"CHECK (status IN ('registered', 'indexing', 'ready', 'error'))"
    )


def downgrade() -> None:
    op.execute(
        f'ALTER TABLE "{SCHEMA}".rag_sources DROP CONSTRAINT IF EXISTS "{CONSTRAINT_DB_NAME}"'
    )
    op.execute(
        f"ALTER TABLE \"{SCHEMA}\".rag_sources "
        f"ADD CONSTRAINT \"{CONSTRAINT_DB_NAME}\" "
        f"CHECK (status IN ('registered'))"
    )
